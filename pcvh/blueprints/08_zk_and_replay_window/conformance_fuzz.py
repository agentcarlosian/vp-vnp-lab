"""Differential Conformance Bridge: O(1) 64-bit Bitmask `prod_zk_replay.py` vs Lean 4 `Specs.ZkReplay.Statement`."""

from __future__ import annotations

import argparse
import os
import pathlib
import random
import shutil
import subprocess
import tempfile
from typing import List

from prod_zk_replay import WireGuardReplayWindow, unpack_bits4, verify_r1cs_range4_and_mux

_LEAN_RUNNER = r"""
import Specs.ZkReplay.Statement
open ZkReplay

def pNat! (s : String) : Nat := s.trimAscii.toString.toNat!

def pInt! (s : String) : Int :=
  let t := s.trimAscii.toString
  if t.startsWith "-" then -Int.ofNat (t.drop 1).toString.toNat!
  else Int.ofNat t.toNat!

def bitmapOfOffsets (offs : List Nat) : Nat :=
  offs.foldl (fun acc d => if d < 64 then acc ||| (1 <<< d) else acc) 0

#eval do
  let raw ← IO.FS.readFile "{DATA_FILE}"
  let lines : List String := (raw.splitOn "\n").map (fun (s : String) => s.trimAscii.toString) |>.filter (fun (s : String) => !s.isEmpty)
  let mut ok := 0
  for line in lines do
    match line.splitOn "|" with
    | [sV, sSel, sA, sB, sExpPack, sExpMux, sSeqs, sExpDecs, sExpHigh, sExpMask] =>
      let v := pNat! sV
      let sel := pInt! sSel
      let a := pInt! sA
      let b := pInt! sB
      let u : Int × Int × Int × Int := unpackBits4 v
      let packed := packBits4 u.1 u.2.1 u.2.2.1 u.2.2.2
      let muxOut := muxGate sel a b
      if packed != pInt! sExpPack || muxOut != pInt! sExpMux then
        throw (IO.userError s!"ZK MISMATCH at trace {ok}")

      let seqs : List Nat := (sSeqs.splitOn ",").map pNat!
      let expDecs : List Bool := (sExpDecs.splitOn ",").map (fun (d : String) => pNat! d == 1)
      let mut w := emptyWindow
      let mut decs : List Bool := []
      for seq in seqs do
        let (acc, w') := acceptPacket w seq
        w := w'
        decs := decs ++ [acc]
      let leanMask := bitmapOfOffsets w.seenOffsets
      if decs != expDecs || w.highest != pNat! sExpHigh || leanMask != pNat! sExpMask then
        throw (IO.userError s!"REPLAY MISMATCH at trace {ok}: lean=({w.highest},{leanMask}) py=({sExpHigh},{sExpMask})")
      ok := ok + 1
    | _ => throw (IO.userError s!"Malformed line: {line}")
  IO.println s!"{ok}/{lines.length} ZK+ReplayWindow 64-bit differential traces matched bit-for-bit"
"""


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
