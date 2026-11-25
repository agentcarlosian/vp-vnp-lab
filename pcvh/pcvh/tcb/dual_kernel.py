"""Independent Dual-Kernel Verification Runner (`lean4export` + `nanoda` / Palomar `comparator`)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import pathlib
import shutil
import subprocess
import time
from typing import Dict, List, Optional, Sequence

from ..config import SpecConfig

# Pinned commits matching Anthropic's `anthropics/formal-math` Palomar CI
DEFAULT_COMPARATOR_COMMIT = "575674928e239f5bc452aab72d1dd7b0f1326494"
DEFAULT_NANODA_COMMIT = "68d5ca9db226849b41a6fff59d796ff19d0a8840"
DEFAULT_LANDRUN_COMMIT = "811cfff51ceaf3d9843708aa6d22e9b84ccac8b4"


@dataclass
class DualKernelResult:
    ok: bool
    status: str           # "PASS" | "FAIL" | "SKIPPED_LOCAL"
    backend: str          # "comparator+nanoda" | "lean4export+nanoda" | "none"
    detail: str
    duration_s: float = 0.0
    exported_lines: int = 0
    raw_output: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "status": self.status,
            "backend": self.backend,
            "detail": self.detail,
            "duration_s": round(self.duration_s, 3),
            "exported_lines": self.exported_lines,
        }


def _find_tool(env_var: str, *names: str) -> Optional[str]:
    override = os.environ.get(env_var)
    if override and pathlib.Path(override).exists():
        return override
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    # Also check standard CI cache location `~/.cache/lean-ci-tools`
    cache_dir = pathlib.Path.home() / ".cache" / "lean-ci-tools"
    if cache_dir.exists():
        extra_paths = [
            cache_dir / "comparator" / ".lake" / "build" / "bin" / "comparator",
            cache_dir / "lean4export" / ".lake" / "build" / "bin" / "lean4export",
            cache_dir / "nanoda" / "target" / "release" / "nanoda_bin",
            cache_dir / "bin" / "landrun",
        ]
        for p in extra_paths:
            if p.name in names and p.exists():
                return str(p)
    return None


def write_palomar_comparator_config(workspace: pathlib.Path, cfg: SpecConfig) -> pathlib.Path:
    """Emit a Palomar-compatible `comparator.json` configuration inside the isolated workspace."""
    payload = {
        "challenge_module": cfg.challenge_module,
        "solution_module": cfg.solution_module,
        "permitted_axioms": list(cfg.allowed_axioms),
        "enable_nanoda": True,
    }
    out_fp = workspace / "comparator.json"
    out_fp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out_fp


def run_dual_kernel_verification(
    workspace: pathlib.Path,
    cfg: SpecConfig,
    *,
    lake_exe: pathlib.Path,
    env: Dict[str, str],
    require_dual_kernel: bool = False,
    target_theorems: Optional[Sequence[str]] = None,
) -> DualKernelResult:
    """Replay compiled Solution proof terms through an independent second Lean 4 kernel (`nanoda`).

    Execution priority:
      1. Full Palomar `comparator` + `lean4export` + `nanoda_bin` (+ `landrun` on Linux).
      2. Direct `lake env lean4export <SolutionModule>` -> `nanoda_bin` kernel replay.
      3. Graceful `SKIPPED_LOCAL` if binaries are absent (or hard `FAIL` when `require_dual_kernel=True`).
    """
    t0 = time.time()
    comp_cfg = write_palomar_comparator_config(workspace, cfg)

    comparator_bin = _find_tool("COMPARATOR_BIN", "comparator", "comparator.exe")
    lean4export_bin = _find_tool("COMPARATOR_LEAN4EXPORT", "lean4export", "lean4export.exe")
    nanoda_bin = _find_tool("COMPARATOR_NANODA", "nanoda_bin", "nanoda", "nanoda_bin.exe", "nanoda.exe")
    landrun_bin = _find_tool("COMPARATOR_LANDRUN", "landrun")

    run_env = dict(env)
    if lean4export_bin:
        run_env["COMPARATOR_LEAN4EXPORT"] = lean4export_bin
    if nanoda_bin:
        run_env["COMPARATOR_NANODA"] = nanoda_bin
    if landrun_bin:
        run_env["COMPARATOR_LANDRUN"] = landrun_bin
    run_env["LEAN_ABORT_ON_PANIC"] = "1"

    # Path 1: Full Palomar `comparator` with `enable_nanoda = true`
    if comparator_bin and lean4export_bin and nanoda_bin and (os.name != "posix" or landrun_bin or os.environ.get("PCVH_ALLOW_NO_LANDRUN")):
        proc = subprocess.run(
            [str(lake_exe), "env", comparator_bin, str(comp_cfg)],
            cwd=str(workspace),
            env=run_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        accepted = proc.returncode == 0 and any(ln.strip() == "Your solution is okay!" for ln in out.splitlines())
        if accepted:
            return DualKernelResult(
                ok=True,
                status="PASS",
                backend="comparator+nanoda",
                detail="Palomar comparator + independent nanoda kernel accepted ('Your solution is okay!')",
                duration_s=time.time() - t0,
                raw_output=out,
            )
        return DualKernelResult(
            ok=False,
            status="FAIL",
            backend="comparator+nanoda",
            detail=f"Palomar comparator+nanoda rejected (rc={proc.returncode}): {out[-400:]}",
            duration_s=time.time() - t0,
            raw_output=out,
        )

    # Path 2: Direct `lean4export` -> `nanoda` independent kernel replay
    if lean4export_bin and nanoda_bin:
        export_fp = workspace / ".pcvh_solution.export"
        decl_names: List[str] = [
            t if "." in t else f"{cfg.solution_module}.{t}"
            for t in (target_theorems or [])
        ]
        exp_cmd = [str(lake_exe), "env", lean4export_bin, cfg.solution_module]
        if decl_names:
            exp_cmd.extend(["--", *decl_names])
        exp_proc = subprocess.run(
            exp_cmd,
            cwd=str(workspace),
            env=run_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if exp_proc.returncode != 0 or not (exp_proc.stdout or "").strip():
            err_out = ((exp_proc.stdout or "") + "\n" + (exp_proc.stderr or "")).strip()
            return DualKernelResult(
                ok=False,
                status="FAIL",
                backend="lean4export+nanoda",
                detail=f"lean4export failed (rc={exp_proc.returncode}): {err_out[-400:]}",
                duration_s=time.time() - t0,
                raw_output=err_out,
            )

        export_fp.write_text(exp_proc.stdout, encoding="utf-8")
        n_lines = exp_proc.stdout.count("\n")

        nanoda_cfg_fp = workspace / ".pcvh_nanoda_config.json"
        nanoda_cfg_payload: Dict[str, object] = {
            "export_file_path": str(export_fp.resolve()),
            "use_stdin": False,
            "permitted_axioms": list(cfg.allowed_axioms),
            "unpermitted_axiom_hard_error": True,
            "num_threads": 2,
            "nat_extension": True,
            "string_extension": True,
            "unknown_pp_declar_hard_error": True,
            "print_success_message": True,
            "print_axioms": True,
        }
        if decl_names:
            nanoda_cfg_payload["pp_declars"] = decl_names
        nanoda_cfg_fp.write_text(json.dumps(nanoda_cfg_payload, indent=2) + "\n", encoding="utf-8")

        nan_proc = subprocess.run(
            [nanoda_bin, str(nanoda_cfg_fp)],
            cwd=str(workspace),
            env=run_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        nan_out = ((nan_proc.stdout or "") + "\n" + (nan_proc.stderr or "")).strip()
        if nan_proc.returncode == 0:
            return DualKernelResult(
                ok=True,
                status="PASS",
                backend="lean4export+nanoda",
                detail=f"Independent nanoda kernel replayed {n_lines} exported proof-term lines in {time.time() - t0:.2f}s",
                duration_s=time.time() - t0,
                exported_lines=n_lines,
                raw_output=nan_out,
            )
        return DualKernelResult(
            ok=False,
            status="FAIL",
            backend="lean4export+nanoda",
            detail=f"Independent nanoda kernel REJECTED exported proof terms (rc={nan_proc.returncode}): {nan_out[-400:]}",
            duration_s=time.time() - t0,
            exported_lines=n_lines,
            raw_output=nan_out,
        )

    # Path 3: Binaries not installed locally
    missing = []
    if not lean4export_bin:
        missing.append("lean4export")
    if not nanoda_bin:
        missing.append("nanoda_bin")
    msg = f"Missing independent kernel tools: {', '.join(missing)}"
    if require_dual_kernel:
        return DualKernelResult(
            ok=False,
            status="FAIL",
            backend="none",
            detail=f"Dual-kernel required but unavailable ({msg}). Install via scripts/setup_dual_kernel_ci.sh.",
            duration_s=time.time() - t0,
        )
    return DualKernelResult(
        ok=True,
        status="SKIPPED_LOCAL",
        backend="none",
        detail=f"Lean 4.33.1 kernel comparator active; {msg} (enforced in Linux CI dual-kernel job)",
        duration_s=time.time() - t0,
    )
