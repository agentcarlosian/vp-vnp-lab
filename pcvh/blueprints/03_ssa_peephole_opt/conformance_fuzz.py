"""Differential Conformance Bridge: compares Python `prod_iropt.py` against Lean 4 `Specs.IrOpt.Statement`."""

from __future__ import annotations

import argparse
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List

from prod_iropt import BinOp, Const, Expr, Var, eval_expr, expr_size, opt_pass


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


def gen_expr(rng: random.Random, depth: int) -> Expr:
    if depth <= 0 or rng.random() < 0.35:
        if rng.random() < 0.55:
            return Const(rng.choice([0, 1, -1, 2, 5, rng.randint(-20, 20)]))
        return Var(rng.randint(0, 3))
    op = rng.choice(["add", "sub", "mul"])
    a = gen_expr(rng, depth - 1)
    # 20% chance of x - x pattern to stress self-subtraction rewrite!
    b = a if (op == "sub" and rng.random() < 0.2) else gen_expr(rng, depth - 1)
    return BinOp(op, a, b)


def serialize_rpn(e: Expr) -> str:
    if isinstance(e, Const):
        return f"C:{e.v}"
    if isinstance(e, Var):
        return f"V:{e.reg}"
    tag = {"add": "A", "sub": "S", "mul": "M"}[e.op]
    return f"{serialize_rpn(e.a)},{serialize_rpn(e.b)},{tag}"


_LEAN_RUNNER = pathlib.Path(__file__).with_name("conformance-oracle.lean.in").read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--traces", type=int, default=500)
    parser.add_argument("--seed", type=int, default=303)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    ws = pathlib.Path(os.environ.get("PCVH_OVERLAY_WS", str(pathlib.Path(__file__).resolve().parent)))
    lean_bin = _resolve_lean_bin(pathlib.Path(__file__).resolve().parent)
    lake_exe = os.path.join(lean_bin, "lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = lean_bin + os.pathsep + env.get("PATH", "")

    rows: List[str] = []
    for _ in range(args.traces):
        e = gen_expr(rng, depth=3)
        reg_vals = [rng.randint(-50, 50) for _ in range(4)]
        env_map: Dict[int, int] = {i: v for i, v in enumerate(reg_vals)}
        oe = opt_pass(e)
        v_orig = eval_expr(env_map, e)
        v_opt = eval_expr(env_map, oe)
        assert v_orig == v_opt and expr_size(oe) <= expr_size(e)
        rows.append(f"{serialize_rpn(e)}|{','.join(str(x) for x in reg_vals)}|{v_opt}|{expr_size(oe)}")

    if os.environ.get("PCVH_EMIT_TRACES") == "1":
        sys.stdout.write("\n".join(rows) + "\n")
        return 0

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write("\n".join(rows) + "\n")
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
        if proc.returncode != 0:
            print(proc.stdout, proc.stderr, file=sys.stderr)
            return proc.returncode
        print(proc.stdout.strip())
        return 0
    finally:
        try:
            data_fp.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
