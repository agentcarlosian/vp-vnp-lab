"""Differential Conformance Bridge: compares Python `prod_vault.py` against Lean 4 `Specs.Vault.Statement`."""

from __future__ import annotations

import argparse
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile
from typing import List

from prod_vault import AmmPool, Erc4626Vault


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

_LEAN_RUNNER = r"""
import Specs.Vault.Statement
open DeFi

def pNat! (s : String) : Nat := s.trimAscii.toString.toNat!

#eval do
  let raw ← IO.FS.readFile "{DATA_FILE}"
  let lines := (raw.splitOn "\n").filter (fun (l : String) => !l.trimAscii.isEmpty)
  let mut ok : Nat := 0
  for line in lines do
    match line.splitOn "|" with
    | [sx, sy, sdx, sexpRx, sexpRy, sexpDy, sA, sS, sdA, sexpM, sexpOut] =>
      let (p1, dy) := ammSwapXForY { reserveX := pNat! sx, reserveY := pNat! sy } (pNat! sdx)
      let (v1, minted) := vaultDeposit { totalAssets := pNat! sA, totalShares := pNat! sS } (pNat! sdA)
      let (_, out) := vaultRedeem v1 minted
      if p1.reserveX != pNat! sexpRx || p1.reserveY != pNat! sexpRy || dy != pNat! sexpDy
         || minted != pNat! sexpM || out != pNat! sexpOut then
        throw (IO.userError s!"MISMATCH at case {ok}")
      ok := ok + 1
    | _ => throw (IO.userError s!"Malformed line: {line}")
  IO.println s!"{ok}/{lines.length} DeFi AMM+Vault differential traces matched bit-for-bit"
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--traces", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=4626)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    ws = pathlib.Path(os.environ.get("PCVH_OVERLAY_WS", str(pathlib.Path(__file__).resolve().parent)))
    lean_bin = _resolve_lean_bin(pathlib.Path(__file__).resolve().parent)
    lake_exe = os.path.join(lean_bin, "lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = lean_bin + os.pathsep + env.get("PATH", "")

    rows: List[str] = []
    for _ in range(args.traces):
        x = rng.randint(1, 10**9)
        y = rng.randint(1, 10**9)
        dx = rng.randint(0, 10**9)
        pool = AmmPool(x, y)
        k0 = pool.pool_k()
        dy = pool.swap_x_for_y(dx)
        assert pool.pool_k() >= k0 and pool.reserve_y > 0

        A = rng.randint(1, 10**9)
        S = rng.randint(1, 10**9)
        dA = rng.randint(0, 10**9)
        v = Erc4626Vault(A, S)
        minted = v.deposit(dA)
        out = v.redeem(minted)
        assert out <= dA

        rows.append(f"{x}|{y}|{dx}|{pool.reserve_x}|{pool.reserve_y}|{dy}|{A}|{S}|{dA}|{minted}|{out}")

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
