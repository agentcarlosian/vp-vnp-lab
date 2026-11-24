"""Zero-dependency local HTTP Studio server for PCVH (`pcvh studio`).

Provides a clean JSON REST API, asynchronous job runner (verify / prove / diff-reprove /
falsify / pin / init), live Lean 4 LSP `$/lean/plainGoal` queries, and Ed25519 DSSE
attestation signature verification, backed by an interactive single-page web UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import pathlib
import sys
import threading
import time
import urllib.parse
import uuid
import webbrowser
from typing import Any, Dict, List, Optional

from ..adapters.scaffolder import SUPPORTED_LANGUAGES, SUPPORTED_TEMPLATES, scaffold_project
from ..agents.llm_providers import describe_available_providers
from ..agents.orchestrator import compute_commit_gated_workers, run_autonomous_prove_pipeline
from ..ci.diff_reprove import run_diff_aware_reprove
from ..config import SpecConfig, load_spec_config
from ..falsify.falsifier import run_falsification_precheck
from ..runtime.lean_diagnostics import LeanLSPClient
from ..tcb.crypto import (
    compute_public_key_id,
    generate_ed25519_keypair,
    sign_attestation_file,
    verify_attestation_signature,
)
from ..tcb.manifest import LOCK_FILENAME, pin_tcb_manifest, verify_tcb_manifest
from ..tcb.palomar_gate import resolve_lean_bin, run_palomar_gate

_SKIP_SCAN_DIRS = {
    ".git",
    ".lake",
    ".elan",
    "__pycache__",
    ".pytest_cache",
    ".pcvh_tcb_snapshot",
    ".lean-orch-backups",
    "target",
    "node_modules",
    "out",
    "cache",
}


@dataclass
class StudioJob:
    job_id: str
    project_id: str
    action: str
    status: str = "queued"  # "queued" | "running" | "succeeded" | "failed"
    started_at: str = ""
    finished_at: str = ""
    duration_s: float = 0.0
    logs: List[str] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project_id": self.project_id,
            "action": self.action,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round(self.duration_s, 3),
            "logs": list(self.logs),
            "result": self.result,
            "error": self.error,
        }


class StudioState:
    """Thread-safe controller backing the PCVH Studio REST API."""

    def __init__(self, root_dir: pathlib.Path, *, lean_bin: Optional[pathlib.Path] = None) -> None:
        self.root_dir = pathlib.Path(root_dir).resolve()
        self.lean_bin = lean_bin
        self._lock = threading.Lock()
        self._jobs: Dict[str, StudioJob] = {}
        self._lsp_pool: Dict[str, tuple[LeanLSPClient, threading.Lock]] = {}
        self._ui_html = (pathlib.Path(__file__).resolve().parent / "ui.html").read_text(encoding="utf-8")

    def close_project_lsp(self, project_id: str) -> None:
        with self._lock:
            entry = self._lsp_pool.pop(project_id, None)
        if entry is not None:
            lsp, lock = entry
            with lock:
                lsp.close()

    def close_all(self) -> None:
        with self._lock:
            entries = list(self._lsp_pool.values())
            self._lsp_pool.clear()
        for lsp, lock in entries:
            with lock:
                lsp.close()

    def _safe_project_path(self, project_id: str) -> pathlib.Path:
        cand = (self.root_dir / project_id).resolve()
        if not cand.is_relative_to(self.root_dir):
            raise ValueError(f"Path outside studio root rejected: {project_id}")
        if not (cand / "pcvh.toml").exists():
            raise FileNotFoundError(f"No pcvh.toml found for project '{project_id}'")
        return cand

    def discover_projects(self) -> List[Dict[str, Any]]:
        found: List[pathlib.Path] = []
        if (self.root_dir / "pcvh.toml").exists():
            found.append(self.root_dir)

        for p in self.root_dir.rglob("pcvh.toml"):
            rel = p.relative_to(self.root_dir)
            if any(part in _SKIP_SCAN_DIRS for part in rel.parts):
                continue
            if p.parent not in found:
                found.append(p.parent)

        projects: List[Dict[str, Any]] = []
        for proj_dir in sorted(found):
            rel_id = "." if proj_dir == self.root_dir else proj_dir.relative_to(self.root_dir).as_posix()
            try:
                cfg = load_spec_config(proj_dir)
                man = verify_tcb_manifest(cfg)
                att_fp = proj_dir / "proof-attestation.json"
                att = json.loads(att_fp.read_text(encoding="utf-8")) if att_fp.exists() else None
                projects.append(
                    {
                        "id": rel_id,
                        "name": cfg.name,
                        "language": cfg.target_language,
                        "template": cfg.target_template,
                        "toolchain": cfg.lean_toolchain,
                        "tcb_pinned": man.lock_exists,
                        "tcb_ok": man.ok,
                        "spec_bundle_sha256": man.spec_bundle_sha256,
                        "verdict": att.get("verdict") if att else "UNVERIFIED",
                        "verified_count": len(att.get("verified_theorems", [])) if att else 0,
                        "axioms_used": att.get("axioms_used", []) if att else [],
                        "signed": bool(att and att.get("signature_envelope")),
                        "has_conformance": bool(cfg.conformance_command),
                    }
                )
            except Exception as exc:
                projects.append({"id": rel_id, "name": proj_dir.name, "verdict": "CONFIG_ERROR", "error": str(exc)})
        return projects

    def get_overview(self) -> Dict[str, Any]:
        resolved_lean = None
        try:
            resolved_lean = str(resolve_lean_bin(self.root_dir, self.lean_bin))
        except FileNotFoundError:
            resolved_lean = None

        safe_workers, commit_gb = compute_commit_gated_workers(4)
        with self._lock:
            recent_jobs = [j.to_dict() for j in reversed(list(self._jobs.values())[-20:])]
        return {
            "root_dir": str(self.root_dir),
            "lean_bin": resolved_lean,
            "commit_avail_gb": round(commit_gb, 2) if commit_gb >= 0 else None,
            "recommended_workers": safe_workers,
            "llm_providers": describe_available_providers(),
            "supported_languages": list(SUPPORTED_LANGUAGES),
            "supported_templates": list(SUPPORTED_TEMPLATES),
            "projects": self.discover_projects(),
            "jobs": recent_jobs,
        }

    def get_project_detail(self, project_id: str) -> Dict[str, Any]:
        proj_dir = self._safe_project_path(project_id)
        cfg = load_spec_config(proj_dir)
        man = verify_tcb_manifest(cfg)
        lock_fp = proj_dir / LOCK_FILENAME
        att_fp = proj_dir / "proof-attestation.json"

        def _read_opt(rel: str) -> str:
            fp = proj_dir / rel
            return fp.read_text(encoding="utf-8", errors="replace") if fp.exists() else ""

        sol_rel = f"{cfg.solution_module.replace('.', '/')}.lean"
        lean_files: List[str] = []
        for lf in sorted(proj_dir.rglob("*.lean")):
            rel = lf.relative_to(proj_dir)
            if any(part in _SKIP_SCAN_DIRS for part in rel.parts):
                continue
            lean_files.append(rel.as_posix())

        files_map: Dict[str, str] = {
            cfg.statement_rel: _read_opt(cfg.statement_rel),
            cfg.challenge_rel: _read_opt(cfg.challenge_rel),
            sol_rel: _read_opt(sol_rel),
        }
        # Expose all synthesized helper lemma modules (`Solution/Lem_*.lean`)
        for lf_rel in lean_files:
            if lf_rel not in files_map:
                files_map[lf_rel] = _read_opt(lf_rel)
        # Expose production target code (`prod_*.py`, `target.py`, `src/lib.rs`, `src/target.ts`, `src/Target.sol`)
        for cand_glob in ("prod_*.py", "target.py", "src/lib.rs", "src/target.ts", "src/Target.sol", "test/Conformance.t.sol"):
            for tf in sorted(proj_dir.glob(cand_glob)):
                rel_t = tf.relative_to(proj_dir).as_posix()
                if rel_t not in files_map:
                    files_map[rel_t] = _read_opt(rel_t)
        files_map["pcvh.toml"] = _read_opt("pcvh.toml")

        return {
            "id": project_id,
            "name": cfg.name,
            "language": cfg.target_language,
            "template": cfg.target_template,
            "toolchain": cfg.lean_toolchain,
            "statement_rel": cfg.statement_rel,
            "challenge_rel": cfg.challenge_rel,
            "solution_rel": sol_rel,
            "conformance_command": cfg.conformance_command,
            "tcb_ok": man.ok,
            "tcb_mismatched": man.mismatched_files,
            "tcb_missing": man.missing_files,
            "lock": json.loads(lock_fp.read_text(encoding="utf-8")) if lock_fp.exists() else None,
            "attestation": json.loads(att_fp.read_text(encoding="utf-8")) if att_fp.exists() else None,
            "lean_files": lean_files,
            "files": files_map,
        }

    def read_project_file(self, project_id: str, rel_file: str) -> str:
        proj_dir = self._safe_project_path(project_id)
        fp = (proj_dir / rel_file).resolve()
        if not fp.is_relative_to(proj_dir) or not fp.exists():
            raise FileNotFoundError(f"File not found inside project: {rel_file}")
        return fp.read_text(encoding="utf-8", errors="replace")

    def _get_or_start_lsp(self, project_id: str, proj_dir: pathlib.Path) -> tuple[LeanLSPClient, threading.Lock]:
        with self._lock:
            existing = self._lsp_pool.get(project_id)
            if existing is not None and not existing[0]._closed:
                return existing
        lsp = LeanLSPClient(proj_dir, lean_bin=self.lean_bin)
        lsp.start()
        lock = threading.Lock()
        with self._lock:
            prev = self._lsp_pool.get(project_id)
            if prev is not None and not prev[0]._closed:
                lsp.close()
                return prev
            self._lsp_pool[project_id] = (lsp, lock)
            return lsp, lock

    def inspect_lsp_goals(self, project_id: str, rel_file: str, line_1idx: int, col_0idx: int = 0) -> Dict[str, Any]:
        proj_dir = self._safe_project_path(project_id)
        fp = (proj_dir / rel_file).resolve()
        if not fp.is_relative_to(proj_dir) or not fp.exists():
            raise FileNotFoundError(f"Lean file not found: {rel_file}")
        text = fp.read_text(encoding="utf-8", errors="replace")
        lsp, lock = self._get_or_start_lsp(project_id, proj_dir)
        try:
            with lock:
                diags, goals, rendered = lsp.evaluate_state(
                    fp,
                    text,
                    max(0, line_1idx - 1),
                    max(0, col_0idx),
                    timeout=20.0,
                )
        except Exception:
            # Restart once if persistent server died
            self.close_project_lsp(project_id)
            lsp, lock = self._get_or_start_lsp(project_id, proj_dir)
            with lock:
                diags, goals, rendered = lsp.evaluate_state(
                    fp,
                    text,
                    max(0, line_1idx - 1),
                    max(0, col_0idx),
                    timeout=20.0,
                )
        return {
            "file": rel_file,
            "line": line_1idx,
            "col": col_0idx,
            "goals": goals,
            "rendered": rendered,
            "diagnostics": [
                {
                    "line": d.line,
                    "column": d.column,
                    "severity": d.severity,
                    "message": d.message,
                }
                for d in diags
            ],
        }

    def sign_project_attestation(self, project_id: str) -> Dict[str, Any]:
        proj_dir = self._safe_project_path(project_id)
        att_fp = proj_dir / "proof-attestation.json"
        if not att_fp.exists():
            raise FileNotFoundError("No proof-attestation.json found yet; run Verify (Palomar Gate) first.")
        key_dir = self.root_dir / ".pcvh_studio_keys"
        priv_fp = key_dir / "pcvh_signing.key.pem"
        pub_fp = key_dir / "pcvh_signing.pub.pem"
        if not priv_fp.exists() or not pub_fp.exists():
            kp = generate_ed25519_keypair(key_dir)
            pub_pem = kp.public_key_pem
            key_id = kp.key_id
        else:
            pub_pem = pub_fp.read_text(encoding="utf-8")
            key_id = compute_public_key_id(pub_pem)
        signed = sign_attestation_file(att_fp, priv_fp, key_id=key_id)
        return {
            "ok": True,
            "key_id": key_id,
            "public_key_pem": pub_pem,
            "attestation_sha256": signed["attestation_sha256"],
        }

    def verify_project_signature(self, project_id: str, public_key_pem: str) -> Dict[str, Any]:
        proj_dir = self._safe_project_path(project_id)
        att_fp = proj_dir / "proof-attestation.json"
        if not att_fp.exists():
            return {"ok": False, "reason": "No proof-attestation.json found for this project."}
        att = json.loads(att_fp.read_text(encoding="utf-8"))
        res = verify_attestation_signature(att, public_key_pem)
        return res.to_dict()

    def scaffold_new_project(self, rel_dir: str, language: str, template: str, name: Optional[str] = None) -> Dict[str, Any]:
        dest = (self.root_dir / rel_dir).resolve()
        if not dest.is_relative_to(self.root_dir):
            raise ValueError("Target directory must stay inside studio root.")
        res = scaffold_project(dest, language=language, template=template, name=name or dest.name, auto_pin=True)
        return res.to_dict()

    def start_action_job(self, project_id: str, action: str, options: Optional[Dict[str, Any]] = None) -> StudioJob:
        proj_dir = self._safe_project_path(project_id)
        opts = options or {}
        if action not in ("verify", "prove", "diff-reprove", "falsify", "pin"):
            raise ValueError(f"Unsupported action: {action}")

        job_id = uuid.uuid4().hex[:10]
        job = StudioJob(
            job_id=job_id,
            project_id=project_id,
            action=action,
            status="running",
            started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            logs=[f"[{action}] Starting on {project_id}..."],
        )
        with self._lock:
            self._jobs[job_id] = job

        def _worker() -> None:
            t0 = time.time()
            try:
                if action in ("verify", "prove", "diff-reprove"):
                    self.close_project_lsp(project_id)
                cfg: SpecConfig = load_spec_config(proj_dir)
                if action == "pin":
                    lock = pin_tcb_manifest(cfg, save_snapshot=True)
                    job.logs.append(f"Pinned {len(lock['files'])} TCB files (sha256={lock['spec_bundle_sha256'][:16]}...).")
                    job.result = lock
                    job.status = "succeeded"
                elif action == "falsify":
                    res = run_falsification_precheck(cfg, lean_bin=self.lean_bin)
                    job.logs.append(f"Falsification status={res.status} ({res.samples_evaluated} samples).")
                    job.result = res.to_dict()
                    job.status = "succeeded" if res.ok else "failed"
                elif action == "verify":
                    att_fp = proj_dir / "proof-attestation.json"
                    res = run_palomar_gate(
                        cfg,
                        lean_bin=self.lean_bin,
                        run_conformance=not bool(opts.get("skip_conformance", False)),
                        require_dual_kernel=bool(opts.get("require_dual_kernel", False)),
                        attestation_out=att_fp,
                    )
                    job.logs.append(f"Palomar verdict={res.verdict} ({len(res.verified_theorems)} theorems, axioms={res.axioms_used}).")
                    job.result = res.to_attestation_dict()
                    job.status = "succeeded" if res.verdict == "VERIFIED" else "failed"
                elif action == "prove":
                    res = run_autonomous_prove_pipeline(
                        cfg,
                        lean_bin=self.lean_bin,
                        llm_provider=opts.get("llm_provider"),
                        llm_model=opts.get("llm_model"),
                        parallel_workers=int(opts.get("parallel_workers", cfg.max_parallel_workers)),
                        attestation_out=proj_dir / "proof-attestation.json",
                    )
                    job.logs.append(
                        f"Autonomous prove status={res.status} (waves={res.waves_executed}, peak_workers={res.peak_parallel_workers})."
                    )
                    job.result = res.to_dict()
                    job.status = "succeeded" if res.status == "VERIFIED" else "failed"
                elif action == "diff-reprove":
                    res = run_diff_aware_reprove(
                        cfg,
                        lean_bin=self.lean_bin,
                        attestation_out=proj_dir / "proof-attestation.json",
                    )
                    job.logs.append(
                        f"Diff-reprove status={res.status} (cached={len(res.cached_theorems)}, reproved={len(res.reproved_theorems)})."
                    )
                    job.result = res.to_dict()
                    job.status = "succeeded" if res.status == "VERIFIED" else "failed"
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
                job.logs.append(f"ERROR: {exc}")
            finally:
                job.duration_s = time.time() - t0
                job.finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        threading.Thread(target=_worker, daemon=True).start()
        return job

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            j = self._jobs.get(job_id)
            return j.to_dict() if j else None


class PCVHStudioServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], state: StudioState) -> None:
        self.studio_state = state
        super().__init__(server_address, _StudioHandler)

    def server_close(self) -> None:
        self.studio_state.close_all()
        super().server_close()


class _StudioHandler(BaseHTTPRequestHandler):
    server: PCVHStudioServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return  # Keep terminal clean unless debugging

    def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        st = self.server.studio_state

        try:
            if parsed.path in ("/", "/index.html"):
                body = st._ui_html.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == "/api/overview":
                self._send_json(HTTPStatus.OK, st.get_overview())
                return

            if parsed.path == "/api/project":
                pid = (qs.get("id") or [""])[0]
                self._send_json(HTTPStatus.OK, st.get_project_detail(pid))
                return

            if parsed.path == "/api/file":
                pid = (qs.get("id") or [""])[0]
                rel = (qs.get("path") or [""])[0]
                content = st.read_project_file(pid, rel)
                self._send_json(HTTPStatus.OK, {"path": rel, "content": content})
                return

            if parsed.path == "/api/job":
                jid = (qs.get("id") or [""])[0]
                job = st.get_job(jid)
                if job is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown job_id: {jid}"})
                else:
                    self._send_json(HTTPStatus.OK, job)
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Not found: {parsed.path}"})
        except FileNotFoundError as exc:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        st = self.server.studio_state
        try:
            body = self._read_json_body()
            if parsed.path == "/api/action":
                pid = str(body.get("project_id", ""))
                action = str(body.get("action", ""))
                opts = body.get("options") if isinstance(body.get("options"), dict) else {}
                job = st.start_action_job(pid, action, opts)
                self._send_json(HTTPStatus.ACCEPTED, job.to_dict())
                return

            if parsed.path == "/api/lsp/goals":
                pid = str(body.get("project_id", ""))
                rel = str(body.get("rel_file", ""))
                line = int(body.get("line", 1))
                col = int(body.get("col", 0))
                res = st.inspect_lsp_goals(pid, rel, line, col)
                self._send_json(HTTPStatus.OK, res)
                return

            if parsed.path == "/api/sign":
                pid = str(body.get("project_id", ""))
                res = st.sign_project_attestation(pid)
                self._send_json(HTTPStatus.OK, res)
                return

            if parsed.path == "/api/verify-sig":
                pid = str(body.get("project_id", ""))
                pub_pem = str(body.get("public_key_pem", ""))
                res = st.verify_project_signature(pid, pub_pem)
                self._send_json(HTTPStatus.OK, res)
                return

            if parsed.path == "/api/init":
                rel_dir = str(body.get("dir", "")).strip()
                lang = str(body.get("language", "rust"))
                tmpl = str(body.get("template", "ratelimit"))
                name = body.get("name")
                if not rel_dir:
                    raise ValueError("Missing 'dir' field.")
                res = st.scaffold_new_project(rel_dir, lang, tmpl, name=name)
                self._send_json(HTTPStatus.CREATED, res)
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Not found: {parsed.path}"})
        except FileNotFoundError as exc:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})


def create_studio_server(
    root_dir: pathlib.Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    lean_bin: Optional[pathlib.Path] = None,
) -> PCVHStudioServer:
    state = StudioState(root_dir, lean_bin=lean_bin)
    return PCVHStudioServer((host, port), state)


def serve_studio(
    root_dir: pathlib.Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    lean_bin: Optional[pathlib.Path] = None,
    open_browser: bool = True,
) -> int:
    srv = create_studio_server(root_dir, host=host, port=port, lean_bin=lean_bin)
    actual_port = srv.server_address[1]
    url = f"http://{host}:{actual_port}"
    print(f"=== PCVH Studio running at {url} ===")
    print(f"Workspace root: {pathlib.Path(root_dir).resolve()}")
    print("Press Ctrl+C to stop.", flush=True)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down PCVH Studio...")
    finally:
        srv.server_close()
    return 0
