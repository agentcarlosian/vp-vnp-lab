import Specs.Ledger.Statement

/-
  Blueprint 4 — Verified Proof Package (`Solution.lean`)
  Zero `sorry`, zero custom axioms, zero Mathlib dependency.
-/

namespace Solution
open Ledger

private theorem totalBalance_applyDelta (m : Balances) (k : Nat) (d : Int) :
    totalBalance (applyDelta m k d) = totalBalance m + d := by
  induction m with
  | nil =>
      simp [applyDelta, totalBalance]
  | cons hd rest ih =>
      rcases hd with ⟨a, b⟩
      simp only [applyDelta, totalBalance]
      split
      · simp only [totalBalance]
        omega
      · simp only [totalBalance, ih]
        omega

private theorem allNonNeg_applyDelta_credit (m : Balances) (k : Nat) (d : Int)
    (hm : allNonNeg m) (hd : 0 ≤ d) :
    allNonNeg (applyDelta m k d) := by
  induction m with
  | nil =>
      exact ⟨hd, trivial⟩
  | cons hd_entry rest ih =>
      rcases hd_entry with ⟨a, b⟩
      rcases hm with ⟨hb, hrest⟩
      simp only [applyDelta]
      split
      · exact ⟨by omega, hrest⟩
      · exact ⟨hb, ih hrest⟩

private theorem allNonNeg_applyDelta_debit (m : Balances) (k : Nat) (amt : Int)
    (hm : allNonNeg m) (hbal : amt ≤ lookupBalance m k) :
    allNonNeg (applyDelta m k (-amt)) := by
  induction m with
  | nil =>
      simp only [lookupBalance] at hbal
      exact ⟨by omega, trivial⟩
  | cons hd_entry rest ih =>
      rcases hd_entry with ⟨a, b⟩
      rcases hm with ⟨hb, hrest⟩
      simp only [applyDelta]
      simp only [lookupBalance] at hbal
      split
      · rename_i heq
        simp only [heq, ↓reduceIte] at hbal
        exact ⟨by omega, hrest⟩
      · rename_i hne
        simp only [hne, ↓reduceIte] at hbal
        exact ⟨hb, ih hrest hbal⟩

theorem step_conserves_total_balance
    (s0 s1 : LedgerState) (ev : TransferEvent)
    (h : step s0 ev = StepResult.ok s1) :
    totalBalance s1.balances = totalBalance s0.balances := by
  unfold step at h
  split at h
  · injection h with hEq
    subst hEq
    rfl
  · split at h
    · cases h
    · split at h
      · cases h
      · injection h with hEq
        subst hEq
        simp only [totalBalance_applyDelta, debitTotal]
        omega

theorem trace_conserves_total_balance
    (s0 : LedgerState) (evs : List TransferEvent) :
    totalBalance (execTrace s0 evs).balances = totalBalance s0.balances := by
  induction evs generalizing s0 with
  | nil => rfl
  | cons ev rest ih =>
      simp only [execTrace]
      cases hstep : step s0 ev with
      | ok s' =>
          rw [ih s', step_conserves_total_balance s0 s' ev hstep]
      | err _ =>
          exact ih s0

theorem step_idempotent_on_seen_key
    (s0 : LedgerState) (ev : TransferEvent)
    (h_seen : ev.idKey ∈ s0.seenKeys) :
    step s0 ev = StepResult.ok s0 := by
  simp [step, h_seen]

private theorem step_preserves_nonneg
    (s0 s1 : LedgerState) (ev : TransferEvent)
    (h_nonneg : allNonNeg s0.balances)
    (h : step s0 ev = StepResult.ok s1) :
    allNonNeg s1.balances := by
  unfold step at h
  split at h
  · injection h with hEq
    subst hEq
    exact h_nonneg
  · split at h
    · cases h
    · split at h
      · cases h
      · rename_i _ _ hnotlt
        injection h with hEq
        subst hEq
        have hge : debitTotal ev ≤ lookupBalance s0.balances ev.fromAcct := by omega
        have h1 := allNonNeg_applyDelta_debit s0.balances ev.fromAcct (debitTotal ev) h_nonneg hge
        have h2 := allNonNeg_applyDelta_credit _ ev.toAcct (ev.amount : Int) h1 (Int.natCast_nonneg ev.amount)
        exact allNonNeg_applyDelta_credit _ ev.feeAcct (ev.fee : Int) h2 (Int.natCast_nonneg ev.fee)

theorem trace_preserves_nonneg_balances
    (s0 : LedgerState) (evs : List TransferEvent)
    (h_nonneg : allNonNeg s0.balances) :
    allNonNeg (execTrace s0 evs).balances := by
  induction evs generalizing s0 with
  | nil => exact h_nonneg
  | cons ev rest ih =>
      simp only [execTrace]
      cases hstep : step s0 ev with
      | ok s' =>
          exact ih s' (step_preserves_nonneg s0 s' ev h_nonneg hstep)
      | err _ =>
          exact ih s0 h_nonneg

private theorem step_seenKeys_monotone
    (s0 s1 : LedgerState) (ev : TransferEvent) (k : Nat)
    (h_in : k ∈ s0.seenKeys)
    (h : step s0 ev = StepResult.ok s1) :
    k ∈ s1.seenKeys := by
  unfold step at h
  split at h
  · injection h with hEq
    subst hEq
    exact h_in
  · split at h
    · cases h
    · split at h
      · cases h
      · injection h with hEq
        subst hEq
        exact List.mem_cons_of_mem ev.idKey h_in

theorem trace_seenKeys_monotone
    (s0 : LedgerState) (evs : List TransferEvent) (k : Nat)
    (h_in : k ∈ s0.seenKeys) :
    k ∈ (execTrace s0 evs).seenKeys := by
  induction evs generalizing s0 with
  | nil => exact h_in
  | cons ev rest ih =>
      simp only [execTrace]
      cases hstep : step s0 ev with
      | ok s' =>
          exact ih s' (step_seenKeys_monotone s0 s' ev k h_in hstep)
      | err _ =>
          exact ih s0 h_in

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
  refine ⟨?_, rfl, rfl, rfl, rfl, ?_, ?_⟩
  · exact ⟨by omega, by omega, by omega, trivial⟩
  · decide
  · decide

end Solution
