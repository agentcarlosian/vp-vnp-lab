import Specs.AgentGuard.Statement

/-
  Blueprint 06 — Verified AI Agent Guardrail Proofs (`Solution.lean`)
  Zero `sorry`, zero custom axioms, zero Mathlib dependency.
-/

namespace Solution
open AgentGuard

private theorem step_preserves_budget
    (pol : Policy) (st : GuardState) (call : ToolCall)
    (h : st.spentCents ≤ pol.maxBudgetCents) :
    (stepState pol st call).spentCents ≤ pol.maxBudgetCents := by
  unfold stepState evalToolCall
  split <;> try split <;> try split <;> try split <;> try split <;> try split
  all_goals (simp_all; try omega)

theorem guard_trace_preserves_budget_cap
    (pol : Policy) (st : GuardState) (calls : List ToolCall)
    (h_init : st.spentCents ≤ pol.maxBudgetCents) :
    (execTrace pol st calls).spentCents ≤ pol.maxBudgetCents := by
  induction calls generalizing st with
  | nil => exact h_init
  | cons hd tl ih =>
    exact ih (stepState pol st hd) (step_preserves_budget pol st hd h_init)

private theorem step_preserves_calls
    (pol : Policy) (st : GuardState) (call : ToolCall)
    (h : st.callCount ≤ pol.maxCalls) :
    (stepState pol st call).callCount ≤ pol.maxCalls := by
  unfold stepState evalToolCall
  split <;> try split <;> try split <;> try split <;> try split <;> try split
  all_goals (simp_all; try omega)

theorem guard_trace_preserves_rate_limit
    (pol : Policy) (st : GuardState) (calls : List ToolCall)
    (h_init : st.callCount ≤ pol.maxCalls) :
    (execTrace pol st calls).callCount ≤ pol.maxCalls := by
  induction calls generalizing st with
  | nil => exact h_init
  | cons hd tl ih =>
    exact ih (stepState pol st hd) (step_preserves_calls pol st hd h_init)

theorem guard_blocks_scope_or_traversal
    (pol : Policy) (st : GuardState) (call : ToolCall)
    (h_bad : call.isPathTraversal = true ∨ call.scopeId ≠ pol.allowedScopeId) :
    (evalToolCall pol st call).1 ≠ Decision.allowed := by
  unfold evalToolCall
  split
  · simp
  · split
    · simp
    · have hcond : (call.isPathTraversal || (call.scopeId != pol.allowedScopeId)) = true := by
        rcases h_bad with h1 | h2
        · simp [h1]
        · simp [bne_iff_ne, h2]
      simp [hcond]

theorem guard_destructive_requires_human_approval
    (pol : Policy) (st : GuardState) (call : ToolCall)
    (h_dest : call.isDestructive = true)
    (h_no_app : call.hasHumanApproval = false) :
    (evalToolCall pol st call).1 ≠ Decision.allowed := by
  unfold evalToolCall
  split
  · simp
  · split
    · simp
    · split
      · simp
      · simp [h_dest, h_no_app]

theorem guard_killswitch_permanent
    (pol : Policy) (st : GuardState) (calls : List ToolCall)
    (h_halt : st.halted = true) :
    execTrace pol st calls = st := by
  induction calls with
  | nil => rfl
  | cons hd tl ih =>
    have hstep : stepState pol st hd = st := by
      unfold stepState evalToolCall
      simp [h_halt]
    simp [execTrace, hstep, ih]

private theorem step_spent_monotone
    (pol : Policy) (st : GuardState) (call : ToolCall) :
    st.spentCents ≤ (stepState pol st call).spentCents := by
  unfold stepState evalToolCall
  split <;> try split <;> try split <;> try split <;> try split <;> try split
  all_goals (simp_all; try omega)

theorem guard_spent_monotone
    (pol : Policy) (st : GuardState) (calls : List ToolCall) :
    st.spentCents ≤ (execTrace pol st calls).spentCents := by
  induction calls generalizing st with
  | nil => exact Nat.le_refl _
  | cons hd tl ih =>
    simp only [execTrace]
    have h1 := step_spent_monotone pol st hd
    have h2 := ih (stepState pol st hd)
    omega

theorem agent_guard_spec_nonvacuous :
    let pol : Policy := { maxBudgetCents := 500, maxCalls := 10, allowedScopeId := 7 }
    let s0  : GuardState := { spentCents := 0, callCount := 0, halted := false }
    let c1  : ToolCall := ⟨7, false, false, false, 120, false⟩
    let c2  : ToolCall := ⟨7, true,  false, true,  10,  false⟩
    let c3  : ToolCall := ⟨7, false, true,  false, 50,  false⟩
    let c4  : ToolCall := ⟨7, false, true,  true,  200, false⟩
    let c5  : ToolCall := ⟨7, false, false, false, 10,  true⟩
    let c6  : ToolCall := ⟨7, false, false, true,  10,  false⟩
    let sf := execTrace pol s0 [c1, c2, c3, c4, c5, c6]
    (evalToolCall pol s0 c2).1 = Decision.deniedScope ∧
    (evalToolCall pol s0 c3).1 = Decision.deniedApproval ∧
    sf = { spentCents := 320, callCount := 2, halted := true } := by
  decide

end Solution
