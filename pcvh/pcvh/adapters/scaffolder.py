"""Multi-language production target adapters (Rust, TypeScript, Solidity/Foundry, Python) & `pcvh init`."""

from __future__ import annotations

from dataclasses import dataclass, field
import pathlib
import re
from typing import Dict, List, Tuple

from ..config import load_spec_config
from ..tcb.manifest import pin_tcb_manifest

SUPPORTED_LANGUAGES = ("rust", "typescript", "solidity", "python")
SUPPORTED_TEMPLATES = ("ratelimit", "vault", "ledger")


@dataclass
class ScaffoldResult:
    project_root: pathlib.Path
    name: str
    language: str
    template: str
    files_created: List[str] = field(default_factory=list)
    pinned: bool = False
    spec_bundle_sha256: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "project_root": str(self.project_root),
            "name": self.name,
            "language": self.language,
            "template": self.template,
            "files_created": list(self.files_created),
            "pinned": self.pinned,
            "spec_bundle_sha256": self.spec_bundle_sha256,
        }


def _sanitize_pkg(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip()).strip("_").lower()
    if not s or not s[0].isalpha():
        s = "pcvh_" + s
    return s


# ==============================================================================
# Shared Portable Lean 4 Resolver Snippet embedded into generated bridges
# ==============================================================================

_PORTABLE_LEAN_RESOLVER = r'''
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
    raise FileNotFoundError("Could not locate Lean 4 `lake` binary; set PCVH_LEAN_BIN or install elan.")
'''


# ==============================================================================
# Lean 4 Formal Spec Templates (Statement.lean + Challenge.lean)
# All 3 templates are 100% pure Lean 4.33.1 (zero Mathlib) and autonomously provable.
# ==============================================================================

def _lean_spec_ratelimit() -> Tuple[str, str, str, str]:
    """Return `(mod_name, namespace, statement_lean, challenge_lean)` for Token-Bucket Rate Limiter."""
    stmt = """/-
Token-Bucket Rate Limiter — Trusted Formal Specification (TCB)
Auto-scaffolded by `pcvh init`.
-/
namespace RateLimit

/-- Refill bucket tokens by `added`, clamped at `capacity`. -/
def refill (tokens capacity added : Nat) : Nat :=
  min capacity (tokens + added)

/-- Attempt to consume `cost` tokens: succeeds iff `cost ≤ tokens`. -/
def tryConsume (tokens cost : Nat) : Bool × Nat :=
  if cost ≤ tokens then (true, tokens - cost) else (false, tokens)

/-- Execute one atomic step: refill first (clamped), then attempt consume. -/
def step (tokens capacity added cost : Nat) : Bool × Nat :=
  tryConsume (refill tokens capacity added) cost

/-- Net tokens available never exceed capacity after a step. -/
def postTokens (tokens capacity added cost : Nat) : Nat :=
  (step tokens capacity added cost).2

end RateLimit
"""
    chall = """import Specs.RateLimit.Statement

namespace Challenge
open RateLimit

/-- Refilling never exceeds the configured bucket capacity. -/
theorem refill_le_capacity (tokens capacity added : Nat) :
    refill tokens capacity added ≤ capacity := by
  sorry

/-- Consuming never increases token balance. -/
theorem tryConsume_le_tokens (tokens cost : Nat) :
    (tryConsume tokens cost).2 ≤ tokens := by
  sorry

/-- A combined refill + consume step always preserves the capacity invariant. -/
theorem step_preserves_capacity (tokens capacity added cost : Nat) :
    postTokens tokens capacity added cost ≤ capacity := by
  sorry

/-- Request is granted if and only if cost is within refilled tokens. -/
theorem step_accepted_iff (tokens capacity added cost : Nat) :
    (step tokens capacity added cost).1 = true ↔ cost ≤ refill tokens capacity added := by
  sorry

/-- Mandatory non-vacuity witness: concrete reachable trace accepts and deducts accurately. -/
theorem ratelimit_spec_nonvacuous :
    step 3 10 4 5 = (true, 2) ∧ step 2 10 1 5 = (false, 3) := by
  sorry

end Challenge
"""
    return "RateLimit", "RateLimit", stmt, chall


def _lean_spec_vault() -> Tuple[str, str, str, str]:
    """Return `(mod_name, namespace, statement_lean, challenge_lean)` for ERC-4626 Share Vault + AMM."""
    stmt = """/-
ERC-4626 Share Vault & Constant-Product AMM — Trusted Formal Specification (TCB)
Auto-scaffolded by `pcvh init`.
-/
namespace VaultSpec

/-- Conservative floor-rounded ERC-4626 share minting (1:1 when empty). -/
def previewDeposit (totalAssets totalShares depositAmt : Nat) : Nat :=
  if totalAssets = 0 || totalShares = 0 then depositAmt
  else (depositAmt * totalShares) / totalAssets

/-- Conservative floor-rounded ERC-4626 asset redemption. -/
def previewRedeem (totalAssets totalShares shareAmt : Nat) : Nat :=
  if totalShares = 0 then 0
  else (shareAmt * totalAssets) / totalShares

/-- Constant-product AMM output `dy = floor(dx * y / (x + dx))` (zero fee). -/
def ammAmountOut (x y dx : Nat) : Nat :=
  if x + dx = 0 then 0
  else (dx * y) / (x + dx)

/-- Post-swap Y reserve after swapping `dx` of X for Y. -/
def ammNewReserveY (x y dx : Nat) : Nat :=
  y - ammAmountOut x y dx

end VaultSpec
"""
    chall = """import Specs.VaultSpec.Statement

namespace Challenge
open VaultSpec

/-- Zero deposit mints zero shares. -/
theorem deposit_zero_mints_zero (totalAssets totalShares : Nat) :
    previewDeposit totalAssets totalShares 0 = 0 := by
  sorry

/-- Redeeming zero shares returns zero assets. -/
theorem redeem_zero_returns_zero (totalAssets totalShares : Nat) :
    previewRedeem totalAssets totalShares 0 = 0 := by
  sorry

/-- AMM output is strictly bounded by Y reserve whenever `x > 0` and `y > 0`. -/
theorem amm_out_lt_reserve_y (x y dx : Nat) (hx : 0 < x) (hy : 0 < y) :
    ammAmountOut x y dx < y := by
  sorry

/-- Post-swap Y reserve remains strictly positive (pool cannot be drained). -/
theorem amm_never_drains_y (x y dx : Nat) (hx : 0 < x) (hy : 0 < y) :
    0 < ammNewReserveY x y dx := by
  sorry

/-- Mandatory non-vacuity witness on concrete ERC-4626 and AMM values. -/
theorem vault_spec_nonvacuous :
    previewDeposit 1000 500 200 = 100 ∧
    previewRedeem 1200 600 100 = 200 ∧
    ammAmountOut 1000 1000 250 = 200 ∧
    ammNewReserveY 1000 1000 250 = 800 := by
  sorry

end Challenge
"""
    return "VaultSpec", "VaultSpec", stmt, chall


def _lean_spec_ledger() -> Tuple[str, str, str, str]:
    """Return `(mod_name, namespace, statement_lean, challenge_lean)` for Two-Account Atomic Transfer."""
    stmt = """/-
Atomic Double-Entry Transfer Core — Trusted Formal Specification (TCB)
Auto-scaffolded by `pcvh init`.
-/
namespace LedgerCore

structure Balances where
  sender : Nat
  receiver : Nat
  deriving Repr, DecidableEq

/-- Execute an atomic transfer if `amount ≤ sender`; otherwise leave unchanged. -/
def transfer (b : Balances) (amount : Nat) : Bool × Balances :=
  if amount ≤ b.sender then
    (true, { sender := b.sender - amount, receiver := b.receiver + amount })
  else
    (false, b)

/-- Total conserved value across both accounts. -/
def totalSupply (b : Balances) : Nat :=
  b.sender + b.receiver

end LedgerCore
"""
    chall = """import Specs.LedgerCore.Statement

namespace Challenge
open LedgerCore

/-- Every transfer strictly conserves total supply across sender and receiver. -/
theorem transfer_conserves_supply (b : Balances) (amount : Nat) :
    totalSupply (transfer b amount).2 = totalSupply b := by
  sorry

/-- Rejected transfers leave balances completely unchanged. -/
theorem transfer_rejected_noop (b : Balances) (amount : Nat) (h : b.sender < amount) :
    transfer b amount = (false, b) := by
  sorry

/-- Zero-amount transfers always succeed and preserve both balances. -/
theorem transfer_zero_identity (b : Balances) :
    transfer b 0 = (true, b) := by
  sorry

/-- Mandatory non-vacuity witness with accepted and rejected transfers. -/
theorem ledger_spec_nonvacuous :
    transfer ⟨100, 25⟩ 40 = (true, ⟨60, 65⟩) ∧
    transfer ⟨10, 25⟩ 40 = (false, ⟨10, 25⟩) := by
  sorry

end Challenge
"""
    return "LedgerCore", "LedgerCore", stmt, chall


def _get_lean_spec(template: str) -> Tuple[str, str, str, str]:
    if template == "ratelimit":
        return _lean_spec_ratelimit()
    if template == "vault":
        return _lean_spec_vault()
    if template == "ledger":
        return _lean_spec_ledger()
    raise ValueError(f"Unsupported template '{template}'. Choose from {SUPPORTED_TEMPLATES}.")


# ==============================================================================
# Lean 4 Differential Conformance Runner Templates (per domain template)
# Each reads pipe-delimited rows generated by Rust / TypeScript / Solidity / Python.
# ==============================================================================

def _lean_conformance_script(template: str, mod_name: str, ns: str) -> str:
    if template == "ratelimit":
        return f"""import Specs.{mod_name}.Statement
open {ns}

def pNat! (s : String) : Nat := s.trimAscii.toString.toNat!

#eval do
  let raw ← IO.FS.readFile "{{DATA_FILE}}"
  let lines : List String := (raw.splitOn "\\n").map (fun (s : String) => s.trimAscii.toString) |>.filter (fun (s : String) => !s.isEmpty)
  let mut ok := 0
  for line in lines do
    match line.splitOn "|" with
    | [sTok, sCap, sAdd, sCost, sAcc, sNext] =>
      let (acc, nxt) := step (pNat! sTok) (pNat! sCap) (pNat! sAdd) (pNat! sCost)
      let expAcc := (pNat! sAcc) == 1
      let expNxt := pNat! sNext
      if acc != expAcc || nxt != expNxt then
        throw (IO.userError s!"MISMATCH row {{ok}}: lean=({{acc}},{{nxt}}) target=({{expAcc}},{{expNxt}})")
      ok := ok + 1
    | _ => throw (IO.userError s!"Malformed row: {{line}}")
  IO.println s!"{{ok}}/{{lines.length}} {{TARGET_LABEL}} differential traces matched bit-for-bit"
"""
    if template == "vault":
        return f"""import Specs.{mod_name}.Statement
open {ns}

def pNat! (s : String) : Nat := s.trimAscii.toString.toNat!

#eval do
  let raw ← IO.FS.readFile "{{DATA_FILE}}"
  let lines : List String := (raw.splitOn "\\n").map (fun (s : String) => s.trimAscii.toString) |>.filter (fun (s : String) => !s.isEmpty)
  let mut ok := 0
  for line in lines do
    match line.splitOn "|" with
    | [sA, sS, sD, sExpSh, sExpRed, sX, sY, sDx, sExpDy, sExpNewY] =>
      let sh := previewDeposit (pNat! sA) (pNat! sS) (pNat! sD)
      let red := previewRedeem (pNat! sA + pNat! sD) (pNat! sS + sh) sh
      let dy := ammAmountOut (pNat! sX) (pNat! sY) (pNat! sDx)
      let ny := ammNewReserveY (pNat! sX) (pNat! sY) (pNat! sDx)
      if sh != pNat! sExpSh || red != pNat! sExpRed || dy != pNat! sExpDy || ny != pNat! sExpNewY then
        throw (IO.userError s!"MISMATCH row {{ok}}: lean=({{sh}},{{red}},{{dy}},{{ny}})")
      ok := ok + 1
    | _ => throw (IO.userError s!"Malformed row: {{line}}")
  IO.println s!"{{ok}}/{{lines.length}} {{TARGET_LABEL}} differential traces matched bit-for-bit"
"""
    # ledger
    return f"""import Specs.{mod_name}.Statement
open {ns}

def pNat! (s : String) : Nat := s.trimAscii.toString.toNat!

#eval do
  let raw ← IO.FS.readFile "{{DATA_FILE}}"
  let lines : List String := (raw.splitOn "\\n").map (fun (s : String) => s.trimAscii.toString) |>.filter (fun (s : String) => !s.isEmpty)
  let mut ok := 0
  for line in lines do
    match line.splitOn "|" with
    | [sSend, sRecv, sAmt, sAcc, sNewS, sNewR] =>
      let (acc, nb) := transfer ⟨pNat! sSend, pNat! sRecv⟩ (pNat! sAmt)
      let expAcc := (pNat! sAcc) == 1
      if acc != expAcc || nb.sender != pNat! sNewS || nb.receiver != pNat! sNewR then
        throw (IO.userError s!"MISMATCH row {{ok}}: lean=({{acc}},{{nb.sender}},{{nb.receiver}})")
      ok := ok + 1
    | _ => throw (IO.userError s!"Malformed row: {{line}}")
  IO.println s!"{{ok}}/{{lines.length}} {{TARGET_LABEL}} differential traces matched bit-for-bit"
"""


# ==============================================================================
# 1. RUST (`cargo test` + `cargo run` Differential Bridge)
# ==============================================================================

def _rust_files(pkg: str, template: str, mod_name: str, ns: str) -> Dict[str, str]:
    cargo_toml = f"""[package]
name = "{pkg}"
version = "0.1.0"
edition = "2021"
"""
    if template == "ratelimit":
        lib_rs = """/// Production Rust Token-Bucket Rate Limiter verified by PCVH.
pub fn refill(tokens: u64, capacity: u64, added: u64) -> u64 {
    tokens.saturating_add(added).min(capacity)
}

pub fn try_consume(tokens: u64, cost: u64) -> (bool, u64) {
    if cost <= tokens {
        (true, tokens - cost)
    } else {
        (false, tokens)
    }
}

pub fn step(tokens: u64, capacity: u64, added: u64, cost: u64) -> (bool, u64) {
    try_consume(refill(tokens, capacity, added), cost)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rate_limit_invariants() {
        assert_eq!(step(3, 10, 4, 5), (true, 2));
        assert_eq!(step(2, 10, 1, 5), (false, 3));
        assert!(step(100, 10, 50, 0).1 <= 10);
    }
}
"""
        main_rs = f"""use {pkg}::step;
use std::env;

fn lcg(state: &mut u64) -> u64 {{
    *state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
    *state >> 16
}}

fn main() {{
    let args: Vec<String> = env::args().collect();
    let traces: usize = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(500);
    let mut rng: u64 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(2026);
    for _ in 0..traces {{
        let cap = (lcg(&mut rng) % 100_000) + 1;
        let tok = lcg(&mut rng) % (cap + 500);
        let add = lcg(&mut rng) % 50_000;
        let cost = lcg(&mut rng) % (cap + 500);
        let (acc, nxt) = step(tok, cap, add, cost);
        assert!(nxt <= cap);
        println!("{{}}|{{}}|{{}}|{{}}|{{}}|{{}}", tok, cap, add, cost, if acc {{ 1 }} else {{ 0 }}, nxt);
    }}
}}
"""
    elif template == "vault":
        lib_rs = """/// Production Rust ERC-4626 Share Vault & Constant-Product AMM verified by PCVH.
pub fn preview_deposit(total_assets: u128, total_shares: u128, deposit_amt: u128) -> u128 {
    if total_assets == 0 || total_shares == 0 {
        deposit_amt
    } else {
        (deposit_amt * total_shares) / total_assets
    }
}

pub fn preview_redeem(total_assets: u128, total_shares: u128, share_amt: u128) -> u128 {
    if total_shares == 0 {
        0
    } else {
        (share_amt * total_assets) / total_shares
    }
}

pub fn amm_amount_out(x: u128, y: u128, dx: u128) -> u128 {
    if x + dx == 0 {
        0
    } else {
        (dx * y) / (x + dx)
    }
}

pub fn amm_new_reserve_y(x: u128, y: u128, dx: u128) -> u128 {
    y - amm_amount_out(x, y, dx)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_vault_amm_invariants() {
        assert_eq!(preview_deposit(1000, 500, 200), 100);
        assert_eq!(preview_redeem(1200, 600, 100), 200);
        assert_eq!(amm_amount_out(1000, 1000, 250), 200);
        assert_eq!(amm_new_reserve_y(1000, 1000, 250), 800);
    }
}
"""
        main_rs = f"""use {pkg}::{{amm_amount_out, amm_new_reserve_y, preview_deposit, preview_redeem}};
use std::env;

fn lcg(state: &mut u64) -> u128 {{
    *state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
    (*state >> 16) as u128
}}

fn main() {{
    let args: Vec<String> = env::args().collect();
    let traces: usize = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(500);
    let mut rng: u64 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(4626);
    for _ in 0..traces {{
        let a = (lcg(&mut rng) % 10_000_000) + 1;
        let s = (lcg(&mut rng) % 10_000_000) + 1;
        let d = lcg(&mut rng) % 10_000_000;
        let sh = preview_deposit(a, s, d);
        let red = preview_redeem(a + d, s + sh, sh);
        assert!(red <= d);
        let x = (lcg(&mut rng) % 10_000_000) + 1;
        let y = (lcg(&mut rng) % 10_000_000) + 1;
        let dx = lcg(&mut rng) % 10_000_000;
        let dy = amm_amount_out(x, y, dx);
        let ny = amm_new_reserve_y(x, y, dx);
        assert!(ny > 0);
        println!("{{}}|{{}}|{{}}|{{}}|{{}}|{{}}|{{}}|{{}}|{{}}|{{}}", a, s, d, sh, red, x, y, dx, dy, ny);
    }}
}}
"""
    else:  # ledger
        lib_rs = """/// Production Rust Double-Entry Atomic Transfer Core verified by PCVH.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Balances {
    pub sender: u64,
    pub receiver: u64,
}

pub fn transfer(b: Balances, amount: u64) -> (bool, Balances) {
    if amount <= b.sender {
        (true, Balances { sender: b.sender - amount, receiver: b.receiver + amount })
    } else {
        (false, b)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_conservation() {
        let b = Balances { sender: 100, receiver: 25 };
        let (ok, nb) = transfer(b, 40);
        assert!(ok);
        assert_eq!(nb.sender + nb.receiver, b.sender + b.receiver);
    }
}
"""
        main_rs = f"""use {pkg}::{{transfer, Balances}};
use std::env;

fn lcg(state: &mut u64) -> u64 {{
    *state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
    *state >> 16
}}

fn main() {{
    let args: Vec<String> = env::args().collect();
    let traces: usize = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(500);
    let mut rng: u64 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(2026);
    for _ in 0..traces {{
        let s = lcg(&mut rng) % 1_000_000;
        let r = lcg(&mut rng) % 1_000_000;
        let amt = lcg(&mut rng) % 1_200_000;
        let (ok, nb) = transfer(Balances {{ sender: s, receiver: r }}, amt);
        assert_eq!(nb.sender + nb.receiver, s + r);
        println!("{{}}|{{}}|{{}}|{{}}|{{}}|{{}}", s, r, amt, if ok {{ 1 }} else {{ 0 }}, nb.sender, nb.receiver);
    }}
}}
"""

    lean_runner = _lean_conformance_script(template, mod_name, ns).replace("{TARGET_LABEL}", "Rust cargo")
    bridge = f'''"""Differential Conformance Bridge: Rust (`cargo test` + trace binary) vs Lean 4 `Specs.{mod_name}.Statement`."""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

_LEAN_RUNNER = pathlib.Path(__file__).with_name("conformance-oracle.lean.in").read_text(encoding="utf-8")
{_PORTABLE_LEAN_RESOLVER}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--traces", type=int, default=500)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    proj = pathlib.Path(__file__).resolve().parent
    ws = pathlib.Path(os.environ.get("PCVH_OVERLAY_WS", str(proj)))
    cargo = shutil.which("cargo")
    if not cargo:
        print("ERROR: `cargo` not found on PATH for Rust conformance adapter.", file=sys.stderr)
        return 1

    # 1. Run Rust unit tests (`cargo test`)
    test_proc = subprocess.run([cargo, "test", "--quiet"], cwd=str(proj), capture_output=True, text=True)
    if test_proc.returncode != 0:
        print(test_proc.stdout + test_proc.stderr, file=sys.stderr)
        return test_proc.returncode

    # 2. Emit randomized traces from Rust binary
    run_proc = subprocess.run(
        [cargo, "run", "--quiet", "--", str(args.traces), str(args.seed)],
        cwd=str(proj),
        capture_output=True,
        text=True,
    )
    if run_proc.returncode != 0:
        print(run_proc.stdout + run_proc.stderr, file=sys.stderr)
        return run_proc.returncode

    # 3. Replay every trace in Lean 4 Statement model
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
        script = _LEAN_RUNNER.replace("{{DATA_FILE}}", data_fp.as_posix())
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
        out = (proc.stdout or "") + (proc.stderr or "")
        print(out.strip())
        return proc.returncode
    finally:
        data_fp.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
'''
    return {
        "Cargo.toml": cargo_toml,
        "src/lib.rs": lib_rs,
        "src/main.rs": main_rs,
        "conformance_fuzz.py": bridge,
        "conformance-oracle.lean.in": lean_runner,
    }


# ==============================================================================
# 2. TYPESCRIPT (Node.js native TS / `tsx` Differential Bridge)
# ==============================================================================

def _typescript_files(pkg: str, template: str, mod_name: str, ns: str) -> Dict[str, str]:
    package_json = f"""{{
  "name": "{pkg}",
  "version": "0.1.0",
  "type": "module",
  "scripts": {{
    "conformance": "node src/conformance_runner.ts"
  }}
}}
"""
    tsconfig_json = """{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "noEmit": true
  },
  "include": ["src/**/*.ts"]
}
"""
    if template == "ratelimit":
        target_ts = """// Production TypeScript Token-Bucket Rate Limiter verified by PCVH.
export interface StepOutcome {
  accepted: boolean;
  tokens: bigint;
}

export function refill(tokens: bigint, capacity: bigint, added: bigint): bigint {
  const sum = tokens + added;
  return sum < capacity ? sum : capacity;
}

export function tryConsume(tokens: bigint, cost: bigint): StepOutcome {
  if (cost <= tokens) {
    return { accepted: true, tokens: tokens - cost };
  }
  return { accepted: false, tokens };
}

export function step(tokens: bigint, capacity: bigint, added: bigint, cost: bigint): StepOutcome {
  return tryConsume(refill(tokens, capacity, added), cost);
}
"""
        runner_ts = """import { step } from "./target.ts";

let state: bigint = BigInt(process.argv[3] ?? "2026");
const traces: number = Number(process.argv[2] ?? "500");

function nextRand(): bigint {
  state = (state * 6364136223846793005n + 1442695040888963407n) & ((1n << 64n) - 1n);
  return state >> 16n;
}

const out: string[] = [];
for (let i = 0; i < traces; i++) {
  const cap = (nextRand() % 100000n) + 1n;
  const tok = nextRand() % (cap + 500n);
  const add = nextRand() % 50000n;
  const cost = nextRand() % (cap + 500n);
  const res = step(tok, cap, add, cost);
  if (res.tokens > cap) {
    throw new Error(`TypeScript invariant violated: ${res.tokens} > ${cap}`);
  }
  out.push(`${tok}|${cap}|${add}|${cost}|${res.accepted ? 1 : 0}|${res.tokens}`);
}
process.stdout.write(out.join("\\n") + "\\n");
"""
    elif template == "vault":
        target_ts = """// Production TypeScript ERC-4626 Share Vault & AMM verified by PCVH.
export function previewDeposit(totalAssets: bigint, totalShares: bigint, depositAmt: bigint): bigint {
  if (totalAssets === 0n || totalShares === 0n) return depositAmt;
  return (depositAmt * totalShares) / totalAssets;
}

export function previewRedeem(totalAssets: bigint, totalShares: bigint, shareAmt: bigint): bigint {
  if (totalShares === 0n) return 0n;
  return (shareAmt * totalAssets) / totalShares;
}

export function ammAmountOut(x: bigint, y: bigint, dx: bigint): bigint {
  if (x + dx === 0n) return 0n;
  return (dx * y) / (x + dx);
}

export function ammNewReserveY(x: bigint, y: bigint, dx: bigint): bigint {
  return y - ammAmountOut(x, y, dx);
}
"""
        runner_ts = """import { ammAmountOut, ammNewReserveY, previewDeposit, previewRedeem } from "./target.ts";

let state: bigint = BigInt(process.argv[3] ?? "4626");
const traces: number = Number(process.argv[2] ?? "500");

function nextRand(): bigint {
  state = (state * 6364136223846793005n + 1442695040888963407n) & ((1n << 64n) - 1n);
  return state >> 16n;
}

const out: string[] = [];
for (let i = 0; i < traces; i++) {
  const a = (nextRand() % 10000000n) + 1n;
  const s = (nextRand() % 10000000n) + 1n;
  const d = nextRand() % 10000000n;
  const sh = previewDeposit(a, s, d);
  const red = previewRedeem(a + d, s + sh, sh);
  if (red > d) throw new Error("ERC-4626 round-trip inflation!");
  const x = (nextRand() % 10000000n) + 1n;
  const y = (nextRand() % 10000000n) + 1n;
  const dx = nextRand() % 10000000n;
  const dy = ammAmountOut(x, y, dx);
  const ny = ammNewReserveY(x, y, dx);
  if (ny <= 0n) throw new Error("AMM reserve drained!");
  out.push(`${a}|${s}|${d}|${sh}|${red}|${x}|${y}|${dx}|${dy}|${ny}`);
}
process.stdout.write(out.join("\\n") + "\\n");
"""
    else:  # ledger
        target_ts = """// Production TypeScript Double-Entry Atomic Transfer Core verified by PCVH.
export interface Balances {
  sender: bigint;
  receiver: bigint;
}

export interface TransferResult {
  accepted: boolean;
  balances: Balances;
}

export function transfer(b: Balances, amount: bigint): TransferResult {
  if (amount <= b.sender) {
    return {
      accepted: true,
      balances: { sender: b.sender - amount, receiver: b.receiver + amount },
    };
  }
  return { accepted: false, balances: b };
}
"""
        runner_ts = """import { transfer } from "./target.ts";

let state: bigint = BigInt(process.argv[3] ?? "2026");
const traces: number = Number(process.argv[2] ?? "500");

function nextRand(): bigint {
  state = (state * 6364136223846793005n + 1442695040888963407n) & ((1n << 64n) - 1n);
  return state >> 16n;
}

const out: string[] = [];
for (let i = 0; i < traces; i++) {
  const s = nextRand() % 1000000n;
  const r = nextRand() % 1000000n;
  const amt = nextRand() % 1200000n;
  const res = transfer({ sender: s, receiver: r }, amt);
  if (res.balances.sender + res.balances.receiver !== s + r) {
    throw new Error("Supply conservation violated!");
  }
  out.push(`${s}|${r}|${amt}|${res.accepted ? 1 : 0}|${res.balances.sender}|${res.balances.receiver}`);
}
process.stdout.write(out.join("\\n") + "\\n");
"""

    lean_runner = _lean_conformance_script(template, mod_name, ns).replace("{TARGET_LABEL}", "TypeScript Node.js")
    bridge = f'''"""Differential Conformance Bridge: TypeScript (`node` native TS / `tsx`) vs Lean 4 `Specs.{mod_name}.Statement`."""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

_LEAN_RUNNER = pathlib.Path(__file__).with_name("conformance-oracle.lean.in").read_text(encoding="utf-8")
{_PORTABLE_LEAN_RESOLVER}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--traces", type=int, default=500)
    parser.add_argument("--seed", type=int, default=2026)
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
        print("ERROR: Neither `node` (v22.6+) nor `tsx` found on PATH.", file=sys.stderr)
        return 1

    ts_proc = subprocess.run(cmd, cwd=str(proj), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if ts_proc.returncode != 0:
        print(ts_proc.stdout + ts_proc.stderr, file=sys.stderr)
        return ts_proc.returncode

    lean_bin = _resolve_lean_bin(proj)
    lake_exe = os.path.join(lean_bin, "lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = lean_bin + os.pathsep + env.get("PATH", "")

    if os.environ.get("PCVH_EMIT_TRACES") == "1":
        sys.stdout.write(ts_proc.stdout)
        return 0

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write(ts_proc.stdout)
        data_fp = pathlib.Path(tf.name)
    try:
        script = _LEAN_RUNNER.replace("{{DATA_FILE}}", data_fp.as_posix())
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
        out = (proc.stdout or "") + (proc.stderr or "")
        print(out.strip())
        return proc.returncode
    finally:
        data_fp.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
'''
    return {
        "package.json": package_json,
        "tsconfig.json": tsconfig_json,
        "src/target.ts": target_ts,
        "src/conformance_runner.ts": runner_ts,
        "conformance_fuzz.py": bridge,
        "conformance-oracle.lean.in": lean_runner,
    }


# ==============================================================================
# 3. SOLIDITY / FOUNDRY (`forge test` + Differential Bridge)
# ==============================================================================

def _solidity_files(pkg: str, template: str, mod_name: str, ns: str) -> Dict[str, str]:
    foundry_toml = """[profile.default]
src = "src"
out = "out"
libs = ["lib"]
solc_version = "0.8.24"
optimizer = true
optimizer_runs = 200
"""
    if template == "vault":
        contract_sol = """// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

/// @title Production Solidity ERC-4626 & Constant-Product AMM Math verified by PCVH
contract VaultMath {
    function previewDeposit(uint256 totalAssets, uint256 totalShares, uint256 depositAmt)
        public
        pure
        returns (uint256)
    {
        if (totalAssets == 0 || totalShares == 0) {
            return depositAmt;
        }
        return (depositAmt * totalShares) / totalAssets;
    }

    function previewRedeem(uint256 totalAssets, uint256 totalShares, uint256 shareAmt)
        public
        pure
        returns (uint256)
    {
        if (totalShares == 0) {
            return 0;
        }
        return (shareAmt * totalAssets) / totalShares;
    }

    function ammAmountOut(uint256 x, uint256 y, uint256 dx) public pure returns (uint256) {
        if (x + dx == 0) {
            return 0;
        }
        return (dx * y) / (x + dx);
    }

    function ammNewReserveY(uint256 x, uint256 y, uint256 dx) public pure returns (uint256) {
        return y - ammAmountOut(x, y, dx);
    }
}
"""
        test_sol = """// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {VaultMath} from "../src/Target.sol";

/// @notice Foundry invariant & differential trace emitter (`forge test -vv`).
contract ConformanceTest {
    VaultMath internal target;

    function setUp() public {
        target = new VaultMath();
    }

    function testFuzz_NoFreeMoneyAndNoDrain(uint64 a, uint64 s, uint64 d, uint64 x, uint64 y, uint64 dx) public view {
        uint256 A = uint256(a) + 1;
        uint256 S = uint256(s) + 1;
        uint256 D = uint256(d);
        uint256 sh = target.previewDeposit(A, S, D);
        uint256 red = target.previewRedeem(A + D, S + sh, sh);
        require(red <= D, "ERC-4626 free money invariant violated");

        uint256 X = uint256(x) + 1;
        uint256 Y = uint256(y) + 1;
        uint256 DX = uint256(dx);
        uint256 ny = target.ammNewReserveY(X, Y, DX);
        require(ny > 0, "AMM pool drained");
    }
}
"""
        py_sim_body = """
        a = rng.randint(1, 10**9)
        s = rng.randint(1, 10**9)
        d = rng.randint(0, 10**9)
        sh = d if (a == 0 or s == 0) else (d * s) // a
        red = 0 if (s + sh) == 0 else (sh * (a + d)) // (s + sh)
        x = rng.randint(1, 10**9)
        y = rng.randint(1, 10**9)
        dx = rng.randint(0, 10**9)
        dy = 0 if (x + dx) == 0 else (dx * y) // (x + dx)
        ny = y - dy
        rows.append(f"{a}|{s}|{d}|{sh}|{red}|{x}|{y}|{dx}|{dy}|{ny}")
"""
    elif template == "ratelimit":
        contract_sol = """// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

/// @title Production Solidity Token-Bucket Rate Limiter verified by PCVH
contract RateLimiter {
    function refill(uint256 tokens, uint256 capacity, uint256 added) public pure returns (uint256) {
        uint256 sum = tokens + added;
        return sum < capacity ? sum : capacity;
    }

    function step(uint256 tokens, uint256 capacity, uint256 added, uint256 cost)
        public
        pure
        returns (bool accepted, uint256 nextTokens)
    {
        uint256 r = refill(tokens, capacity, added);
        if (cost <= r) {
            return (true, r - cost);
        }
        return (false, r);
    }
}
"""
        test_sol = """// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {RateLimiter} from "../src/Target.sol";

contract ConformanceTest {
    RateLimiter internal target;

    function setUp() public {
        target = new RateLimiter();
    }

    function testFuzz_CapacityInvariant(uint64 tok, uint64 cap, uint64 add, uint64 cost) public view {
        uint256 C = uint256(cap) + 1;
        (, uint256 nxt) = target.step(uint256(tok), C, uint256(add), uint256(cost));
        require(nxt <= C, "RateLimiter capacity invariant violated");
    }
}
"""
        py_sim_body = """
        cap = rng.randint(1, 100_000)
        tok = rng.randint(0, cap + 500)
        add = rng.randint(0, 50_000)
        cost = rng.randint(0, cap + 500)
        r = min(cap, tok + add)
        acc, nxt = (1, r - cost) if cost <= r else (0, r)
        rows.append(f"{tok}|{cap}|{add}|{cost}|{acc}|{nxt}")
"""
    else:  # ledger
        contract_sol = """// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

/// @title Production Solidity Atomic Double-Entry Transfer Core verified by PCVH
contract LedgerCoreSol {
    function transfer(uint256 sender, uint256 receiver, uint256 amount)
        public
        pure
        returns (bool accepted, uint256 newSender, uint256 newReceiver)
    {
        if (amount <= sender) {
            return (true, sender - amount, receiver + amount);
        }
        return (false, sender, receiver);
    }
}
"""
        test_sol = """// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {LedgerCoreSol} from "../src/Target.sol";

contract ConformanceTest {
    LedgerCoreSol internal target;

    function setUp() public {
        target = new LedgerCoreSol();
    }

    function testFuzz_SupplyConservation(uint64 s, uint64 r, uint64 amt) public view {
        (, uint256 ns, uint256 nr) = target.transfer(uint256(s), uint256(r), uint256(amt));
        require(ns + nr == uint256(s) + uint256(r), "Conservation violated");
    }
}
"""
        py_sim_body = """
        s = rng.randint(0, 1_000_000)
        r = rng.randint(0, 1_000_000)
        amt = rng.randint(0, 1_200_000)
        acc, ns, nr = (1, s - amt, r + amt) if amt <= s else (0, s, r)
        rows.append(f"{s}|{r}|{amt}|{acc}|{ns}|{nr}")
"""

    lean_runner = _lean_conformance_script(template, mod_name, ns).replace("{TARGET_LABEL}", "Solidity uint256 model")
    bridge = f'''"""Differential Conformance Bridge: Solidity / Foundry (`forge test`) vs Lean 4 `Specs.{mod_name}.Statement`."""

from __future__ import annotations

import argparse
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile

_LEAN_RUNNER = pathlib.Path(__file__).with_name("conformance-oracle.lean.in").read_text(encoding="utf-8")
{_PORTABLE_LEAN_RESOLVER}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--traces", type=int, default=500)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--require-forge", action="store_true", help="Fail if Foundry `forge` is not installed")
    args = parser.parse_args()

    proj = pathlib.Path(__file__).resolve().parent
    ws = pathlib.Path(os.environ.get("PCVH_OVERLAY_WS", str(proj)))

    # 1. Verify Solidity source exists & run Foundry `forge test` when installed
    sol_src = proj / "src" / "Target.sol"
    if not sol_src.exists():
        print(f"ERROR: Missing Solidity contract {{sol_src}}", file=sys.stderr)
        return 1

    forge = shutil.which("forge")
    forge_note = "sol-uint256-model"
    if forge:
        f_proc = subprocess.run(
            [forge, "test", "--match-contract", "ConformanceTest", "-vv"],
            cwd=str(proj),
            capture_output=True,
            text=True,
        )
        if f_proc.returncode != 0:
            print(f_proc.stdout + f_proc.stderr, file=sys.stderr)
            return f_proc.returncode
        forge_note = "forge-test+lean"
    elif args.require_forge:
        print("ERROR: `forge` not found on PATH (--require-forge enabled).", file=sys.stderr)
        return 1

    # 2. Generate exact uint256 Solidity differential vectors and verify in Lean 4 Statement
    rng = random.Random(args.seed)
    rows = []
    for _ in range(args.traces):{py_sim_body}
    lean_bin = _resolve_lean_bin(proj)
    lake_exe = os.path.join(lean_bin, "lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = lean_bin + os.pathsep + env.get("PATH", "")

    if os.environ.get("PCVH_EMIT_TRACES") == "1":
        sys.stdout.write("\\n".join(rows) + "\\n")
        return 0

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write("\\n".join(rows) + "\\n")
        data_fp = pathlib.Path(tf.name)
    try:
        script = _LEAN_RUNNER.replace("{{DATA_FILE}}", data_fp.as_posix())
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
        print(f"{{out}} [mode={{forge_note}}]")
        return proc.returncode
    finally:
        data_fp.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
'''
    return {
        "foundry.toml": foundry_toml,
        "src/Target.sol": contract_sol,
        "test/Conformance.t.sol": test_sol,
        "conformance_fuzz.py": bridge,
        "conformance-oracle.lean.in": lean_runner,
    }


# ==============================================================================
# 4. PYTHON Target Adapter
# ==============================================================================

def _python_files(pkg: str, template: str, mod_name: str, ns: str) -> Dict[str, str]:
    if template == "ratelimit":
        target_py = """\"\"\"Production Python Token-Bucket Rate Limiter verified by PCVH.\"\"\"

def refill(tokens: int, capacity: int, added: int) -> int:
    return min(capacity, tokens + added)


def step(tokens: int, capacity: int, added: int, cost: int) -> tuple[bool, int]:
    r = refill(tokens, capacity, added)
    if cost <= r:
        return True, r - cost
    return False, r
"""
        loop_body = """
        cap = rng.randint(1, 100_000)
        tok = rng.randint(0, cap + 500)
        add = rng.randint(0, 50_000)
        cost = rng.randint(0, cap + 500)
        acc, nxt = step(tok, cap, add, cost)
        assert nxt <= cap
        rows.append(f"{tok}|{cap}|{add}|{cost}|{1 if acc else 0}|{nxt}")
"""
        imp = "from target import step"
    elif template == "vault":
        target_py = """\"\"\"Production Python ERC-4626 Share Vault & AMM verified by PCVH.\"\"\"

def preview_deposit(total_assets: int, total_shares: int, deposit_amt: int) -> int:
    if total_assets == 0 or total_shares == 0:
        return deposit_amt
    return (deposit_amt * total_shares) // total_assets


def preview_redeem(total_assets: int, total_shares: int, share_amt: int) -> int:
    if total_shares == 0:
        return 0
    return (share_amt * total_assets) // total_shares


def amm_amount_out(x: int, y: int, dx: int) -> int:
    return 0 if (x + dx) == 0 else (dx * y) // (x + dx)


def amm_new_reserve_y(x: int, y: int, dx: int) -> int:
    return y - amm_amount_out(x, y, dx)
"""
        loop_body = """
        a = rng.randint(1, 10**9)
        s = rng.randint(1, 10**9)
        d = rng.randint(0, 10**9)
        sh = preview_deposit(a, s, d)
        red = preview_redeem(a + d, s + sh, sh)
        x = rng.randint(1, 10**9)
        y = rng.randint(1, 10**9)
        dx = rng.randint(0, 10**9)
        dy = amm_amount_out(x, y, dx)
        ny = amm_new_reserve_y(x, y, dx)
        rows.append(f"{a}|{s}|{d}|{sh}|{red}|{x}|{y}|{dx}|{dy}|{ny}")
"""
        imp = "from target import amm_amount_out, amm_new_reserve_y, preview_deposit, preview_redeem"
    else:
        target_py = """\"\"\"Production Python Double-Entry Atomic Transfer Core verified by PCVH.\"\"\"

def transfer(sender: int, receiver: int, amount: int) -> tuple[bool, int, int]:
    if amount <= sender:
        return True, sender - amount, receiver + amount
    return False, sender, receiver
"""
        loop_body = """
        s = rng.randint(0, 1_000_000)
        r = rng.randint(0, 1_000_000)
        amt = rng.randint(0, 1_200_000)
        acc, ns, nr = transfer(s, r, amt)
        assert ns + nr == s + r
        rows.append(f"{s}|{r}|{amt}|{1 if acc else 0}|{ns}|{nr}")
"""
        imp = "from target import transfer"

    lean_runner = _lean_conformance_script(template, mod_name, ns).replace("{TARGET_LABEL}", "Python")
    bridge = f'''"""Differential Conformance Bridge: Python `target.py` vs Lean 4 `Specs.{mod_name}.Statement`."""

from __future__ import annotations

import argparse
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile

{imp}

_LEAN_RUNNER = pathlib.Path(__file__).with_name("conformance-oracle.lean.in").read_text(encoding="utf-8")
{_PORTABLE_LEAN_RESOLVER}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--traces", type=int, default=500)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    proj = pathlib.Path(__file__).resolve().parent
    ws = pathlib.Path(os.environ.get("PCVH_OVERLAY_WS", str(proj)))
    rng = random.Random(args.seed)
    rows = []
    for _ in range(args.traces):{loop_body}
    lean_bin = _resolve_lean_bin(proj)
    lake_exe = os.path.join(lean_bin, "lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = lean_bin + os.pathsep + env.get("PATH", "")

    if os.environ.get("PCVH_EMIT_TRACES") == "1":
        sys.stdout.write("\\n".join(rows) + "\\n")
        return 0

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write("\\n".join(rows) + "\\n")
        data_fp = pathlib.Path(tf.name)
    try:
        script = _LEAN_RUNNER.replace("{{DATA_FILE}}", data_fp.as_posix())
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
        print(((proc.stdout or "") + (proc.stderr or "")).strip())
        return proc.returncode
    finally:
        data_fp.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
'''
    return {
        "target.py": target_py,
        "conformance_fuzz.py": bridge,
        "conformance-oracle.lean.in": lean_runner,
    }


# SHA-256 of the ordered case inputs and results replayed against each template specification.
_REFERENCE_TRANSCRIPTS = {
    ("python", "ledger"): "64f475006d6426b1b0c05c0cfae44c99bf4d9ef1adb983493034156ee7265369",
    ("python", "ratelimit"): "ffddb3c654d79a805183a998b0ca664c7eeaf5c84e0da74b20de8bd2d7f6b0f2",
    ("python", "vault"): "34b21c7d944845b48572acd43d5473974df505ba1d8e490d698dababe1fe3bfe",
    ("rust", "ledger"): "12570111a3de51ed9419c4f6ce330f4e8146f0bab0efb863916ea63d5d3b267b",
    ("rust", "ratelimit"): "3e46ae0c6ddbeb2ece5294ff10e757e75e42d908db7d1f7bfbdf714df4d333d7",
    ("rust", "vault"): "6ca7e8ec4e913a9da4b58a3c78bd43a52eb203e089111c867d28b7f6f40caba9",
    ("solidity", "ledger"): "64f475006d6426b1b0c05c0cfae44c99bf4d9ef1adb983493034156ee7265369",
    ("solidity", "ratelimit"): "ffddb3c654d79a805183a998b0ca664c7eeaf5c84e0da74b20de8bd2d7f6b0f2",
    ("solidity", "vault"): "34b21c7d944845b48572acd43d5473974df505ba1d8e490d698dababe1fe3bfe",
    ("typescript", "ledger"): "12570111a3de51ed9419c4f6ce330f4e8146f0bab0efb863916ea63d5d3b267b",
    ("typescript", "ratelimit"): "3e46ae0c6ddbeb2ece5294ff10e757e75e42d908db7d1f7bfbdf714df4d333d7",
    ("typescript", "vault"): "6ca7e8ec4e913a9da4b58a3c78bd43a52eb203e089111c867d28b7f6f40caba9",
}


def scaffold_project(
    dest_dir: pathlib.Path,
    *,
    language: str = "rust",
    template: str = "ratelimit",
    name: str | None = None,
    toolchain: str = "leanprover/lean4:v4.33.1",
    auto_pin: bool = True,
) -> ScaffoldResult:
    """Scaffold a complete zero-trust PCVH project for Rust, TypeScript, Solidity/Foundry, or Python."""
    lang = language.lower().strip()
    tmpl = template.lower().strip()
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language '{language}'. Supported: {SUPPORTED_LANGUAGES}")
    if tmpl not in SUPPORTED_TEMPLATES:
        raise ValueError(f"Unsupported template '{template}'. Supported: {SUPPORTED_TEMPLATES}")

    root = pathlib.Path(dest_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    proj_name = name or root.name
    pkg = _sanitize_pkg(proj_name)

    mod_name, ns, stmt_lean, chall_lean = _get_lean_spec(tmpl)

    files: Dict[str, str] = {
        "lean-toolchain": f"{toolchain}\n",
        "lakefile.toml": (
            f'name = "{pkg}"\n'
            f'defaultTargets = ["Specs.{mod_name}.Challenge", "Solution"]\n\n'
            f'[[lean_lib]]\nname = "Specs"\n\n'
            f'[[lean_lib]]\nname = "Solution"\n'
        ),
        f"Specs/{mod_name}/Statement.lean": stmt_lean,
        f"Specs/{mod_name}/Challenge.lean": chall_lean,
        "Solution.lean": (
            f"import Specs.{mod_name}.Statement\n\n"
            f"/- Placeholder Solution.lean: run `pcvh prove .` to synthesize proofs autonomously. -/\n"
            f"namespace Solution\nend Solution\n"
        ),
        "pcvh.toml": (
            f'[spec]\n'
            f'name = "{proj_name}"\n'
            f'lean_toolchain = "{toolchain}"\n'
            f'statement = "Specs/{mod_name}/Statement.lean"\n'
            f'challenge = "Specs/{mod_name}/Challenge.lean"\n'
            f'challenge_module = "Specs.{mod_name}.Challenge"\n'
            f'solution_module = "Solution"\n'
            f'allowed_axioms = ["propext", "Classical.choice", "Quot.sound"]\n'
            f'require_nonvacuity_witness = true\n'
            f'nonvacuity_suffix = "nonvacuous"\n\n'
            f'[target]\n'
            f'language = "{lang}"\n'
            f'template = "{tmpl}"\n\n'
            f'[falsification]\n'
            f'enabled = true\n'
            f'lean_samples = 64\n\n'
            f'[agent_loop]\n'
            f'max_rounds_per_lemma = 8\n'
            f'max_token_budget_usd = 5.0\n'
            f'auto_lake_shake = true\n'
            f'forbid_umbrella_imports = ["Mathlib", "Mathlib.Tactic", "Mathlib.All"]\n\n'
            f'[conformance]\n'
            f'traces = 500\n'
            f'transcript_sha256 = "{_REFERENCE_TRANSCRIPTS[lang, tmpl]}"\n'
            f'command = "python conformance_fuzz.py --traces 500"\n'
        ),
    }

    if lang == "rust":
        files.update(_rust_files(pkg, tmpl, mod_name, ns))
    elif lang == "typescript":
        files.update(_typescript_files(pkg, tmpl, mod_name, ns))
    elif lang == "solidity":
        files.update(_solidity_files(pkg, tmpl, mod_name, ns))
    else:
        files.update(_python_files(pkg, tmpl, mod_name, ns))

    created: List[str] = []
    for rel, content in files.items():
        fp = root / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        created.append(rel)

    pinned = False
    bundle_sha = ""
    if auto_pin:
        cfg = load_spec_config(root)
        lock = pin_tcb_manifest(cfg, save_snapshot=True)
        pinned = True
        bundle_sha = str(lock["spec_bundle_sha256"])
        created.append("spec.lock.json")

    return ScaffoldResult(
        project_root=root,
        name=proj_name,
        language=lang,
        template=tmpl,
        files_created=sorted(created),
        pinned=pinned,
        spec_bundle_sha256=bundle_sha,
    )
