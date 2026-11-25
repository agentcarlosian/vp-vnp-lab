#!/usr/bin/env python3
"""Check Remark N.6 in a disposable checkout of the pinned upstream project."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

UPSTREAM_SHA = "11b6c7e3c927df2658f513b6b68ea7f8929c62c5"
TOOLCHAIN = "4.33.1"
HERE = Path(__file__).resolve().parent
ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
SHORT_THEOREMS = {"RemarkN6.computes_det_of_affine", "RemarkN6.remarkN6_of_mainTheoremApprox"}
FULL_THEOREMS = {
    "Solution.mainTheorem",
    "Solution.separation",
    "Solution.mainTheoremApprox",
    "Solution.separationClosure",
    "Solution.permanent_over_real",
    "remarkN6_unconditional",
}


def run(args: list[str], cwd: Path, *, capture: bool = False, env: dict[str, str] | None = None) -> str:
    print(f"+ {shlex.join(args)}", flush=True)
    result = subprocess.run(
        args, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    output = result.stdout or ""
    if capture:
        print(output, end="", flush=True)
    result.check_returncode()
    return output


def check_axioms(output: str, expected: set[str]) -> None:
    seen = set()
    for theorem, values in re.findall(r"^'([^']+)' depends on axioms: \[([^\]]*)\]", output, re.M):
        axioms = {value.strip() for value in values.split(",") if value.strip()}
        if unexpected := axioms - ALLOWED_AXIOMS:
            raise ValueError(f"{theorem} uses unexpected axioms: {', '.join(sorted(unexpected))}")
        seen.add(theorem)
    seen.update(re.findall(r"^'([^']+)' does not depend on any axioms", output, re.M))
    if missing := expected - seen:
        raise ValueError(f"Missing axiom report for: {', '.join(sorted(missing))}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path, help="disposable formal-math checkout root (not its vp-vnp subdirectory)")
    parser.add_argument("--skip-cache", action="store_true", help="reuse Mathlib cache already fetched in this checkout")
    parser.add_argument("--full", action="store_true", help="also build and check the upstream Solution composition")
    parser.add_argument("--batch-size", type=int, help="build the full Solution with the commit-aware batched script")
    args = parser.parse_args()
    if args.batch_size is not None and (not args.full or args.batch_size < 1):
        parser.error("--batch-size requires --full and a positive value")

    upstream = args.upstream.resolve()
    project = upstream / "vp-vnp"
    try:
        if not (project / "lakefile.toml").is_file():
            raise ValueError(f"Expected a formal-math checkout with vp-vnp/lakefile.toml: {upstream}")
        actual = run(["git", "rev-parse", "HEAD"], upstream, capture=True).strip()
        if actual != UPSTREAM_SHA:
            raise ValueError(f"Expected upstream revision {UPSTREAM_SHA}, found {actual}")
        if run(["git", "status", "--porcelain", "--untracked-files=no"], upstream, capture=True).strip():
            raise ValueError("Upstream tracked files are modified; use a clean disposable checkout")
        version = run(["lake", "env", "lean", "--version"], project, capture=True)
        if f"version {TOOLCHAIN}," not in version:
            raise ValueError(f"Expected Lean {TOOLCHAIN}")
        if not args.skip_cache:
            run(["lake", "exe", "cache", "get"], project)

        files = ("RemarkN6.lean", "scripts/CheckRemarkN6.lean", "scripts/CheckFullVerification.lean")
        for name in files:
            src, dest = HERE / name, project / name
            if dest.is_symlink() or (dest.exists() and dest.read_bytes() != src.read_bytes()):
                raise ValueError(f"Won't overwrite a different file: {dest}")
        for name in files:
            src, dest = HERE / name, project / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)

        run(["lake", "build", "Statement"], project)
        output = Path(".lake") / "build" / "lib" / "lean" / "RemarkN6.olean"
        (project / output).parent.mkdir(parents=True, exist_ok=True)
        run(["lake", "env", "lean", "-o", str(output), "RemarkN6.lean"], project)
        check_axioms(
            run(["lake", "env", "lean", "scripts/CheckRemarkN6.lean"], project, capture=True),
            SHORT_THEOREMS,
        )
        if args.full:
            if args.batch_size is not None:
                env = {**os.environ, "VP_VNP_DIR": str(project)}
                batched = str(HERE.parent / "scripts" / "build_lean_batched.py")
                run([sys.executable, batched, str(args.batch_size), "Solution"], project, env=env)
            else:
                run(["lake", "build", "Solution"], project)
            check_axioms(
                run(["lake", "env", "lean", "scripts/CheckFullVerification.lean"], project, capture=True),
                FULL_THEOREMS,
            )
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"Remark N.6 verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
