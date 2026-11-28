"""Differential Conformance Bridge: O(1) 64-bit Bitmask `prod_zk_replay.py` vs Lean 4 `Specs.ZkReplay.Statement`."""

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

from prod_zk_replay import WireGuardReplayWindow, unpack_bits4, verify_r1cs_range4_and_mux

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
    parser.add_argument("--seed", type=int, default=909)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    proj = pathlib.Path(__file__).resolve().parent
    ws = pathlib.Path(os.environ.get("PCVH_OVERLAY_WS", str(proj)))
    lean_bin = _resolve_lean_bin(proj)
    lake_exe = os.path.join(lean_bin, "lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = lean_bin + os.pathsep + env.get("PATH", "")

    rows: List[str] = []
    for _ in range(args.traces):
        v = rng.randint(0, 15)
        sel = rng.choice([0, 1])
        a = rng.randint(-500, 500)
        b = rng.randint(-500, 500)
        packed, mux_out = verify_r1cs_range4_and_mux(v, sel, a, b)
        assert packed == v and mux_out == (a if sel == 1 else b)

        win = WireGuardReplayWindow()
        base = rng.randint(50, 300)
        seqs: List[int] = []
        decs: List[int] = []
        for _step in range(16):
            # Mix advancing packets, out-of-order window packets, exact replays, and >64 stale packets
            mode = rng.random()
            if mode < 0.35 and seqs:
                seq = rng.choice(seqs)  # deliberate replay!
            elif mode < 0.70:
                seq = max(0, base + rng.randint(-30, 25))
            elif mode < 0.88:
                seq = max(0, base - rng.randint(64, 120))  # stale outside window
            else:
                base += rng.randint(1, 80)  # jump window forward
                seq = base
            seqs.append(seq)
            decs.append(1 if win.accept_packet(seq) else 0)

        rows.append(
            f"{v}|{sel}|{a}|{b}|{packed}|{mux_out}|"
            f"{','.join(str(x) for x in seqs)}|{','.join(str(d) for d in decs)}|{win.highest}|{win.bitmap}"
        )

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
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        print(out)
        return proc.returncode
    finally:
        data_fp.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
