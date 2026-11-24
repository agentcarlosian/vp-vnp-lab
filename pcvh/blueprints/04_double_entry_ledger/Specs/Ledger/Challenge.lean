import Specs.Ledger.Statement

/-
  Blueprint 4 — Human-Audited TCB Target Theorems (`Challenge.lean`)
  Every theorem in `namespace Challenge` MUST be proved with exact DefEq type in `Solution.lean`
  using only standard Lean axioms `[propext, Classical.choice, Quot.sound]`.
-/

namespace Challenge
open Ledger

/-- 1. Single-step exact double-entry conservation of total system balance. -/
theorem step_conserves_total_balance
    (s0 s1 : LedgerState) (ev : TransferEvent)
    (h : step s0 ev = StepResult.ok s1) :
    totalBalance s1.balances = totalBalance s0.balances := by
  sorry

/-- 2. Arbitrary-trace exact conservation of total system balance. -/
theorem trace_conserves_total_balance
    (s0 : LedgerState) (evs : List TransferEvent) :
    totalBalance (execTrace s0 evs).balances = totalBalance s0.balances := by
  sorry

/-- 3. Zero double-spend: replaying any already-processed idempotency key is an exact no-op. -/
theorem step_idempotent_on_seen_key
    (s0 : LedgerState) (ev : TransferEvent)
    (h_seen : ev.idKey ∈ s0.seenKeys) :
    step s0 ev = StepResult.ok s0 := by
  sorry

/-- 4. Overdraft impossibility: non-negative balances are preserved across all event streams. -/
theorem trace_preserves_nonneg_balances
    (s0 : LedgerState) (evs : List TransferEvent)
    (h_nonneg : allNonNeg s0.balances) :
    allNonNeg (execTrace s0 evs).balances := by
  sorry

/-- 5. Idempotency-key monotonicity: committed keys can never be forgotten by subsequent events. -/
theorem trace_seenKeys_monotone
    (s0 : LedgerState) (evs : List TransferEvent) (k : Nat)
    (h_in : k ∈ s0.seenKeys) :
    k ∈ (execTrace s0 evs).seenKeys := by
  sorry

/-- 6. Mandatory non-vacuity witness: concrete 3-event trace (transfer + duplicate replay + return)
       moves real value, ignores the replay, and preserves total balance. -/
theorem ledger_spec_nonvacuous :
    let s0 : LedgerState := { balances := [(1, 1000), (2, 0), (99, 0)], seenKeys := [] }
    let ev1 : TransferEvent := { idKey := 101, fromAcct := 1, toAcct := 2, feeAcct := 99, amount := 300, fee := 10 }
    let ev2 : TransferEvent := { idKey := 101, fromAcct := 1, toAcct := 2, feeAcct := 99, amount := 300, fee := 10 }
    let ev3 : TransferEvent := { idKey := 102, fromAcct := 2, toAcct := 1, feeAcct := 99, amount := 100, fee := 5 }
    let s1 := execTrace s0 [ev1, ev2, ev3]
    allNonNeg s0.balances ∧
    lookupBalance s1.balances 1 = 790 ∧
    lookupBalance s1.balances 2 = 195 ∧
    lookupBalance s1.balances 99 = 15 ∧
    totalBalance s1.balances = 1000 ∧
    101 ∈ s1.seenKeys ∧ 102 ∈ s1.seenKeys := by
  sorry

end Challenge
