"""Differential Conformance Bridge: Rust `cargo test` + `src/lib.rs` vs Lean 4 `Specs.OrderBook.Statement`."""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

_LEAN_RUNNER = pathlib.Path(__file__).with_name("conformance-oracle.lean.in").read_text(encoding="utf-8")


def _resolve_lean_bin(start: pathlib.Path) -> str:
    exe = "lake.exe" if os.name == "nt" else "lake"
    if os.environ.get("PCVH_LEAN_BIN"):
        return os.environ["PCVH_LEAN_BIN"]
    candidates = []
    if os.environ.get("ELAN_HOME"):
        candidates.append(pathlib.Path(os.environ["ELAN_HOME"]))
    for anc in [start, *start.parents[:6]]:
        if (anc / ".elan").exists():
            candidates.append(anc / ".elan")
    if (pathlib.Path.home() / ".elan").exists():
        candidates.append(pathlib.Path.home() / ".elan")
    for elan in candidates:
        tcs = elan / "toolchains"
        if tcs.exists():
            pref = tcs / "leanprover--lean4---v4.33.1" / "bin"
            if (pref / exe).exists():
                return str(pref)
            for child in sorted(tcs.iterdir(), reverse=True):
                if (child / "bin" / exe).exists():
                    return str(child / "bin")
    w = shutil.which("lake")
    if w:
        return str(pathlib.Path(w).parent)
    raise FileNotFoundError("Could not locate Lean 4 `lake` binary; set PCVH_LEAN_BIN or install via elan.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--traces", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=808)
    args = parser.parse_args()

    proj = pathlib.Path(__file__).resolve().parent
    ws = pathlib.Path(os.environ.get("PCVH_OVERLAY_WS", str(proj)))
    cargo = shutil.which("cargo")
    if not cargo:
        cand = pathlib.Path.home() / ".cargo" / "bin" / ("cargo.exe" if os.name == "nt" else "cargo")
        if cand.exists():
            cargo = str(cand)
    if not cargo:
        print("ERROR: `cargo` not found on PATH for Blueprint 07 Rust conformance.", file=sys.stderr)
        return 1
    cargo_env = os.environ.copy()
    cargo_bin_dir = str(pathlib.Path(cargo).parent)
    cargo_env["PATH"] = cargo_bin_dir + os.pathsep + cargo_env.get("PATH", "")

    # 1. Run Rust unit tests (`cargo test`)
    test_proc = subprocess.run([cargo, "test", "--quiet"], cwd=str(proj), env=cargo_env, capture_output=True, text=True)
    if test_proc.returncode != 0:
        print(test_proc.stdout + test_proc.stderr, file=sys.stderr)
        return test_proc.returncode

    # 2. Emit 1,000 randomized orderbook + margin traces from Rust binary
    run_proc = subprocess.run(
        [cargo, "run", "--quiet", "--", str(args.traces), str(args.seed)],
        cwd=str(proj),
        env=cargo_env,
        capture_output=True,
        text=True,
    )
    if run_proc.returncode != 0:
        print(run_proc.stdout + run_proc.stderr, file=sys.stderr)
        return run_proc.returncode

    # 3. Verify every trace bit-for-bit against Lean 4 Statement
    lean_bin = _resolve_lean_bin(proj)
    lake_exe = os.path.join(lean_bin, "lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = lean_bin + os.pathsep + env.get("PATH", "")

    if os.environ.get("PCVH_EMIT_TRACES") == "1":
        sys.stdout.write(run_proc.stdout)
        return 0

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write(run_proc.stdout)
        data_fp = pathlib.Path(tf.name)
    try:
        script = _LEAN_RUNNER.replace("{DATA_FILE}", data_fp.as_posix())
        proc = subprocess.run(
            [lake_exe, "env", "lean", "--stdin"],
            input=script,
            cwd=str(ws),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        print(out)
        return proc.returncode
    finally:
        data_fp.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
