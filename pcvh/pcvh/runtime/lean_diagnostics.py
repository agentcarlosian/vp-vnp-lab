"""Structured Lean 4 JSON diagnostics and live headless LSP (`$/lean/plainGoal`) client."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import pathlib
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from ..tcb.palomar_gate import _run_with_transient_oom_retry, resolve_lean_bin


@dataclass(frozen=True)
class LeanDiagnostic:
    file: str
    line: int          # 1-indexed
    column: int        # 0-indexed
    severity: str      # "error" | "warning" | "information"
    message: str
    kind: str = ""

    def format_compact(self) -> str:
        return f"{self.file}:{self.line}:{self.column} [{self.severity}] {self.message}"


@dataclass
class CheckFileResult:
    ok: bool
    returncode: int
    diagnostics: List[LeanDiagnostic] = field(default_factory=list)
    unsolved_goals: List[str] = field(default_factory=list)
    raw_output: str = ""

    @property
    def errors(self) -> List[LeanDiagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]


def check_lean_file_json(
    project_root: pathlib.Path,
    file_path: pathlib.Path,
    *,
    lean_bin: Optional[pathlib.Path] = None,
) -> CheckFileResult:
    """Run `lake env lean --json <file>` and parse structured diagnostics & unsolved goals."""
    lean_bin_dir = resolve_lean_bin(project_root, lean_bin)
    lake_exe = lean_bin_dir / ("lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = str(lean_bin_dir) + os.pathsep + env.get("PATH", "")

    proc = _run_with_transient_oom_retry(
        [str(lake_exe), "env", "lean", "--json", str(file_path)],
        cwd=project_root,
        env=env,
    )
    raw = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    diags: List[LeanDiagnostic] = []
    goals: List[str] = []

    for line in (proc.stdout or "").splitlines():
        s = line.strip()
        if not s.startswith("{"):
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        pos = obj.get("pos") or {}
        sev = str(obj.get("severity", "error")).lower()
        msg = str(obj.get("data", ""))
        kind = str(obj.get("kind", ""))
        fname = str(obj.get("fileName", file_path.name))
        d = LeanDiagnostic(
            file=fname,
            line=int(pos.get("line", 1)),
            column=int(pos.get("column", 0)),
            severity=sev,
            message=msg,
            kind=kind,
        )
        diags.append(d)
        if "unsolved goals" in msg or "⊢" in msg:
            goals.append(msg)

    has_err = proc.returncode != 0 or any(d.severity == "error" for d in diags)
    return CheckFileResult(
        ok=not has_err,
        returncode=proc.returncode,
        diagnostics=diags,
        unsolved_goals=goals,
        raw_output=raw,
    )


class LeanLSPClient:
    """Minimal headless JSON-RPC 2.0 client for `lake env lean --server` supporting `$/lean/plainGoal`."""

    def __init__(
        self,
        project_root: pathlib.Path,
        *,
        lean_bin: Optional[pathlib.Path] = None,
    ) -> None:
        self.project_root = pathlib.Path(project_root).resolve()
        self.lean_bin_dir = resolve_lean_bin(self.project_root, lean_bin)
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._req_id = 0
        self._responses: Dict[int, Dict[str, Any]] = {}
        self._diagnostics_by_uri: Dict[str, List[Dict[str, Any]]] = {}
        self._file_done_events: Dict[str, threading.Event] = {}
        self._doc_versions: Dict[str, int] = {}
        self._cond = threading.Condition()
        self._reader_thread: Optional[threading.Thread] = None
        self._closed = False

    def __enter__(self) -> "LeanLSPClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        lake_exe = self.lean_bin_dir / ("lake.exe" if os.name == "nt" else "lake")
        env = os.environ.copy()
        env["PATH"] = str(self.lean_bin_dir) + os.pathsep + env.get("PATH", "")

        self._proc = subprocess.Popen(
            [str(lake_exe), "env", "lean", "--server"],
            cwd=str(self.project_root),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

        root_uri = self.project_root.as_uri()
        self._request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": root_uri,
                "capabilities": {},
            },
            timeout=25.0,
        )
        self._notify("initialized", {})

    def _send(self, payload: Dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        body = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self._proc.stdin.write(header + body)
        self._proc.stdin.flush()

    def _notify(self, method: str, params: Dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: Dict[str, Any], timeout: float = 20.0) -> Dict[str, Any]:
        with self._cond:
            self._req_id += 1
            rid = self._req_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})

        deadline = time.time() + timeout
        with self._cond:
            while rid not in self._responses and not self._closed:
                rem = deadline - time.time()
                if rem <= 0:
                    raise TimeoutError(f"Lean LSP request {method} (id={rid}) timed out after {timeout}s")
                self._cond.wait(timeout=rem)
            if rid not in self._responses:
                raise RuntimeError(f"Lean LSP server closed while awaiting {method}")
            return self._responses.pop(rid)

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        stream = self._proc.stdout
        try:
            while True:
                headers: Dict[str, str] = {}
                while True:
                    line = stream.readline()
                    if not line:
                        return
                    s = line.decode("ascii", errors="replace").strip()
                    if not s:
                        break
                    if ":" in s:
                        k, v = s.split(":", 1)
                        headers[k.strip().lower()] = v.strip()
                length = int(headers.get("content-length", "0"))
                if length <= 0:
                    continue
                body = stream.read(length)
                if not body:
                    return
                msg = json.loads(body.decode("utf-8", errors="replace"))
                with self._cond:
                    if "id" in msg and ("result" in msg or "error" in msg):
                        self._responses[int(msg["id"])] = msg
                        self._cond.notify_all()
                    elif msg.get("method") == "textDocument/publishDiagnostics":
                        params = msg.get("params") or {}
                        uri = params.get("uri", "")
                        self._diagnostics_by_uri[uri] = params.get("diagnostics", [])
                    elif msg.get("method") == "$/lean/fileProgress":
                        params = msg.get("params") or {}
                        uri = (params.get("textDocument") or {}).get("uri", "")
                        processing = params.get("processing", [])
                        if not processing and uri in self._file_done_events:
                            self._file_done_events[uri].set()
        except Exception:
            pass
        finally:
            with self._cond:
                self._closed = True
                self._cond.notify_all()

    def open_file(self, file_path: pathlib.Path, text: Optional[str] = None, wait_s: float = 20.0) -> str:
        fp = pathlib.Path(file_path).resolve()
        uri = fp.as_uri()
        content = text if text is not None else fp.read_text(encoding="utf-8", errors="replace")
        if uri in self._doc_versions:
            return self.update_file(fp, content, wait_s=wait_s)
        ev = threading.Event()
        with self._cond:
            self._file_done_events[uri] = ev
            self._diagnostics_by_uri[uri] = []
            self._doc_versions[uri] = 1
        self._notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "lean4",
                    "version": 1,
                    "text": content,
                }
            },
        )
        ev.wait(timeout=wait_s)
        return uri

    def update_file(self, file_path: pathlib.Path, text: str, wait_s: float = 15.0) -> str:
        """Incrementally update an open Lean document via `textDocument/didChange` (reusing compiled imports)."""
        fp = pathlib.Path(file_path).resolve()
        uri = fp.as_uri()
        if uri not in self._doc_versions:
            return self.open_file(fp, text=text, wait_s=wait_s)
        ev = threading.Event()
        with self._cond:
            ver = self._doc_versions[uri] + 1
            self._doc_versions[uri] = ver
            self._file_done_events[uri] = ev
            self._diagnostics_by_uri[uri] = []
        self._notify(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": ver},
                "contentChanges": [{"text": text}],
            },
        )
        ev.wait(timeout=wait_s)
        return uri

    def evaluate_state(
        self,
        file_path: pathlib.Path,
        text: str,
        line_0idx: int,
        col_0idx: int,
        *,
        timeout: float = 15.0,
    ) -> Tuple[List[LeanDiagnostic], List[str], Optional[str]]:
        """Sync document via `didOpen`/`didChange` and return `(diagnostics, goals_at_pos, rendered_md)`."""
        uri = self.open_file(file_path, text=text, wait_s=timeout)
        # Brief yield so trailing publishDiagnostics arrives before reading
        time.sleep(0.03)
        resp = self._request(
            "$/lean/plainGoal",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line_0idx, "character": col_0idx},
            },
            timeout=timeout,
        )
        result = resp.get("result")
        goals = [str(g) for g in (result.get("goals") or [])] if result else []
        rendered = str(result.get("rendered")) if (result and result.get("rendered") is not None) else None
        diags = self.get_diagnostics(file_path)
        return diags, goals, rendered

    def get_plain_goal(
        self,
        file_path: pathlib.Path,
        line_0idx: int,
        col_0idx: int,
        *,
        text: Optional[str] = None,
        timeout: float = 15.0,
    ) -> Tuple[List[str], Optional[str]]:
        """Query `$/lean/plainGoal` at (line_0idx, col_0idx) and return `(goals_list, rendered_md)`."""
        uri = self.open_file(file_path, text=text, wait_s=timeout)
        resp = self._request(
            "$/lean/plainGoal",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line_0idx, "character": col_0idx},
            },
            timeout=timeout,
        )
        result = resp.get("result")
        if not result:
            return [], None
        goals = [str(g) for g in (result.get("goals") or [])]
        rendered = result.get("rendered")
        return goals, str(rendered) if rendered is not None else None

    def get_diagnostics(self, file_path: pathlib.Path) -> List[LeanDiagnostic]:
        uri = pathlib.Path(file_path).resolve().as_uri()
        raw = self._diagnostics_by_uri.get(uri, [])
        sev_map = {1: "error", 2: "warning", 3: "information", 4: "hint"}
        out: List[LeanDiagnostic] = []
        for d in raw:
            start = (d.get("range") or {}).get("start") or {}
            out.append(
                LeanDiagnostic(
                    file=file_path.name,
                    line=int(start.get("line", 0)) + 1,
                    column=int(start.get("character", 0)),
                    severity=sev_map.get(int(d.get("severity", 1)), "error"),
                    message=str(d.get("message", "")),
                )
            )
        return out

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            self._notify("exit", {})
        except Exception:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=3)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None
