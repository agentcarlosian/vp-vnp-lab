"""Differential Conformance Bridge: TypeScript `src/agent_guard.ts` vs Lean 4 `Specs.AgentGuard.Statement`."""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

_LEAN_RUNNER = r"""
import Specs.AgentGuard.Statement
open AgentGuard

def pNat! (s : String) : Nat := s.trimAscii.toString.toNat!

def parseCall (tok : String) : IO ToolCall :=
  match tok.splitOn ":" with
  | [sScope, sTrav, sDest, sApp, sCost, sKill] =>
    pure { scopeId := pNat! sScope,
           isPathTraversal := pNat! sTrav == 1,
           isDestructive := pNat! sDest == 1,
           hasHumanApproval := pNat! sApp == 1,
           costCents := pNat! sCost,
           tripKillSwitch := pNat! sKill == 1 }
  | _ => throw (IO.userError s!"Malformed call: {tok}")

#eval do
  let raw ← IO.FS.readFile "{DATA_FILE}"
  let lines : List String := (raw.splitOn "\n").map (fun (s : String) => s.trimAscii.toString) |>.filter (fun (s : String) => !s.isEmpty)
  let mut ok := 0
  for line in lines do
    match line.splitOn "|" with
    | [sBud, sMaxC, sScope, sCalls, sExpDecs, sExpSpent, sExpCnt, sExpHalt] =>
      let pol : Policy := { maxBudgetCents := pNat! sBud, maxCalls := pNat! sMaxC, allowedScopeId := pNat! sScope }
      let calls ← (sCalls.splitOn ",").mapM parseCall
      let expDecs : List Nat := (sExpDecs.splitOn ",").map pNat!
      let mut st : GuardState := { spentCents := 0, callCount := 0, halted := false }
      let mut decs : List Nat := []
      for c in calls do
        let (d, st') := evalToolCall pol st c
        st := st'
        decs := decs ++ [d.code]
      let sf := execTrace pol { spentCents := 0, callCount := 0, halted := false } calls
      if decs != expDecs || st != sf || sf.spentCents != pNat! sExpSpent || sf.callCount != pNat! sExpCnt || sf.halted != (pNat! sExpHalt == 1) then
        throw (IO.userError s!"AGENT GUARD MISMATCH at trace {ok}")
      ok := ok + 1
    | _ => throw (IO.userError s!"Malformed row: {line}")
  IO.println s!"{ok}/{lines.length} TypeScript AI Agent Guardrail 12-step traces matched bit-for-bit"
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
    parser.add_argument("--seed", type=int, default=606)
    args = parser.parse_args()

    proj = pathlib.Path(__file__).resolve().parent
    ws = pathlib.Path(os.environ.get("PCVH_OVERLAY_WS", str(proj)))
    runner = proj / "src" / "conformance_runner.ts"

    node = shutil.which("node")
    tsx = shutil.which("tsx")
    if node:
        cmd = [node, str(runner), str(args.traces), str(args.seed)]
    elif tsx:
        cmd = [tsx, str(runner), str(args.traces), str(args.seed)]
    else:
        print("ERROR: Neither `node` nor `tsx` found on PATH.", file=sys.stderr)
        return 1

    ts_proc = subprocess.run(cmd, cwd=str(proj), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if ts_proc.returncode != 0:
        print(ts_proc.stdout + ts_proc.stderr, file=sys.stderr)
        return ts_proc.returncode

    lean_bin = _resolve_lean_bin(proj)
    lake_exe = os.path.join(lean_bin, "lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = lean_bin + os.pathsep + env.get("PATH", "")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write(ts_proc.stdout)
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
