"""Fast Differential Conformance Bridge: compares Python `prod_ledger.py` against Lean 4 `Specs.Ledger.Statement`.

Passes randomized traces via a compact runtime data file read by Lean `#eval` so thousands of
multi-step traces verify bit-for-bit in ~2 seconds with zero Lean elaborator overhead.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile
from typing import List, Tuple

from prod_ledger import DoubleEntryLedger, TransferEvent


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

ACCOUNTS = [1, 2, 3, 4, 99]


def generate_random_trace(rng: random.Random, steps: int) -> Tuple[List[Tuple[int, int]], List[TransferEvent]]:
    init_balances = [(a, rng.randint(0, 2000)) for a in ACCOUNTS]
    events: List[TransferEvent] = []
    used_keys: List[int] = []
    for step_idx in range(steps):
        if used_keys and rng.random() < 0.25:
            id_key = rng.choice(used_keys)
        else:
            id_key = 1000 + step_idx
            used_keys.append(id_key)
        from_a = rng.choice(ACCOUNTS)
        to_a = rng.choice(ACCOUNTS)
        fee_a = rng.choice(ACCOUNTS)
        amount = 0 if rng.random() < 0.1 else rng.randint(1, 1500)
        fee = rng.randint(0, 100)
        events.append(TransferEvent(id_key, from_a, to_a, fee_a, amount, fee))
    return init_balances, events


def encode_trace_line(
    init_bals: List[Tuple[int, int]],
    events: List[TransferEvent],
    exp_bals: List[int],
    exp_keys: List[int],
) -> str:
    # Format: initB | events | expB | expKeys
    # initB:  a:b,a:b,...
    # events: k:f:t:fe:amt:fee;...
    # expB:   b1,b2,...
    # expKeys: k1,k2,...
    s_init = ",".join(f"{a}:{b}" for a, b in init_bals)
    s_evs = ";".join(
        f"{e.id_key}:{e.from_acct}:{e.to_acct}:{e.fee_acct}:{e.amount}:{e.fee}"
        for e in events
    )
    s_expb = ",".join(str(x) for x in exp_bals)
    s_expk = ",".join(str(k) for k in exp_keys)
    return f"{s_init}|{s_evs}|{s_expb}|{s_expk}"


_LEAN_CONFORMANCE_RUNNER = r"""
import Specs.Ledger.Statement
open Ledger

def accts : List Nat := [1, 2, 3, 4, 99]

def parseNat! (s : String) : Nat := s.trimAscii.toString.toNat!
def parseInt! (s : String) : Int := s.trimAscii.toString.toInt!

def parseInit (s : String) : Balances :=
  if s.trimAscii.isEmpty then []
  else (s.splitOn ",").map fun pair =>
    match pair.splitOn ":" with
    | [a, b] => (parseNat! a, parseInt! b)
    | _ => (0, 0)

def parseEvents (s : String) : List TransferEvent :=
  if s.trimAscii.isEmpty then []
  else (s.splitOn ";").map fun ev =>
    match ev.splitOn ":" with
    | [k, f, t, fe, amt, fee] =>
      { idKey := parseNat! k, fromAcct := parseNat! f, toAcct := parseNat! t,
        feeAcct := parseNat! fe, amount := parseNat! amt, fee := parseNat! fee }
    | _ => { idKey := 0, fromAcct := 0, toAcct := 0, feeAcct := 0, amount := 0, fee := 0 }

def parseInts (s : String) : List Int :=
  if s.trimAscii.isEmpty then [] else (s.splitOn ",").map parseInt!

def parseNats (s : String) : List Nat :=
  if s.trimAscii.isEmpty then [] else (s.splitOn ",").map parseNat!

#eval do
  let raw ← IO.FS.readFile "{DATA_FILE}"
  let lines := (raw.splitOn "\n").filter (fun (l : String) => !l.trimAscii.isEmpty)
  let mut okCount : Nat := 0
  for line in lines do
    match line.splitOn "|" with
    | [sInit, sEvs, sExpB, sExpK] =>
      let initB := parseInit sInit
      let evs := parseEvents sEvs
      let expB := parseInts sExpB
      let expK := parseNats sExpK
      let s1 := execTrace { balances := initB, seenKeys := [] } evs
      let gotB := accts.map (lookupBalance s1.balances)
      let gotK := s1.seenKeys.mergeSort (· ≤ ·)
      if gotB != expB || gotK != expK then
        throw (IO.userError s!"MISMATCH at trace {okCount}: gotB={gotB} expB={expB} gotK={gotK} expK={expK}")
      okCount := okCount + 1
    | _ =>
      throw (IO.userError s!"Malformed trace line: {line}")
  IO.println s!"{okCount}/{lines.length} differential traces matched bit-for-bit"
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Differential conformance bridge: prod_ledger.py vs Lean Statement")
    parser.add_argument("--traces", type=int, default=1000)
    parser.add_argument("--steps-per-trace", type=int, default=10)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    ws = pathlib.Path(os.environ.get("PCVH_OVERLAY_WS", str(pathlib.Path(__file__).resolve().parent)))
    lean_bin = _resolve_lean_bin(pathlib.Path(__file__).resolve().parent)
    lake_exe = os.path.join(lean_bin, "lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = lean_bin + os.pathsep + env.get("PATH", "")

    lines: List[str] = []
    for idx in range(args.traces):
        init_bals, events = generate_random_trace(rng, args.steps_per_trace)
        led = DoubleEntryLedger(balances=dict(init_bals))
        init_total = led.total_balance()
        led.exec_trace(events)

        assert led.total_balance() == init_total, f"Trace {idx}: Python conservation failed!"
        assert all(v >= 0 for v in led.balances.values()), f"Trace {idx}: Python overdraft!"

        exp_bals = [led.balance_of(a) for a in ACCOUNTS]
        exp_keys = sorted(led.seen_keys)
        lines.append(encode_trace_line(init_bals, events, exp_bals, exp_keys))

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write("\n".join(lines) + "\n")
        data_path = pathlib.Path(tf.name)

    try:
        script = _LEAN_CONFORMANCE_RUNNER.replace("{DATA_FILE}", data_path.as_posix())
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
            data_path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
