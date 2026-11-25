import Specs.AgentGuard.Statement

/-
  Blueprint 06 — Human-Audited TCB Target Theorems (`Challenge.lean`)
  Safety invariants for autonomous AI agent tool-execution proxies / MCP gateways.
-/

namespace Challenge
open AgentGuard

/-- 1. Hard Budget Ceiling: across arbitrary multi-step tool call chains, cumulative agent spend
       can NEVER exceed `pol.maxBudgetCents`. -/
theorem guard_trace_preserves_budget_cap
    (pol : Policy) (st : GuardState) (calls : List ToolCall)
    (h_init : st.spentCents ≤ pol.maxBudgetCents) :
    (execTrace pol st calls).spentCents ≤ pol.maxBudgetCents := by
  sorry

/-- 2. Hard Call-Rate Ceiling: cumulative allowed tool invocations never exceed `pol.maxCalls`. -/
theorem guard_trace_preserves_rate_limit
    (pol : Policy) (st : GuardState) (calls : List ToolCall)
    (h_init : st.callCount ≤ pol.maxCalls) :
    (execTrace pol st calls).callCount ≤ pol.maxCalls := by
  sorry

/-- 3. Capability & Path-Traversal Confinement: any tool call escaping workspace scope or containing
       path traversal (`..`) is unconditionally denied. -/
theorem guard_blocks_scope_or_traversal
    (pol : Policy) (st : GuardState) (call : ToolCall)
    (h_bad : call.isPathTraversal = true ∨ call.scopeId ≠ pol.allowedScopeId) :
    (evalToolCall pol st call).1 ≠ Decision.allowed := by
  sorry

/-- 4. Mandatory Human-in-the-Loop Gate: destructive actions without explicit human approval
       can NEVER be allowed. -/
theorem guard_destructive_requires_human_approval
    (pol : Policy) (st : GuardState) (call : ToolCall)
    (h_dest : call.isDestructive = true)
    (h_no_app : call.hasHumanApproval = false) :
    (evalToolCall pol st call).1 ≠ Decision.allowed := by
  sorry

/-- 5. Emergency Kill-Switch Irreversibility: once `halted = true`, the state is frozen across
       every subsequent tool call stream (zero spend, zero calls, cannot un-halt). -/
theorem guard_killswitch_permanent
    (pol : Policy) (st : GuardState) (calls : List ToolCall)
    (h_halt : st.halted = true) :
    execTrace pol st calls = st := by
  sorry

/-- 6. Spend Monotonicity: cumulative `spentCents` is monotonically non-decreasing (prevents
       synthetic refund/underflow budget resets). -/
theorem guard_spent_monotone
    (pol : Policy) (st : GuardState) (calls : List ToolCall) :
    st.spentCents ≤ (execTrace pol st calls).spentCents := by
  sorry

/-- 7. Mandatory non-vacuity witness: concrete 5-call agent trace exercising allowed spend,
       blocked traversal, blocked unapproved delete, approved delete, and kill-switch freeze. -/
theorem agent_guard_spec_nonvacuous :
    let pol : Policy := { maxBudgetCents := 500, maxCalls := 10, allowedScopeId := 7 }
    let s0  : GuardState := { spentCents := 0, callCount := 0, halted := false }
    let c1  : ToolCall := ⟨7, false, false, false, 120, false⟩ -- allowed
    let c2  : ToolCall := ⟨7, true,  false, true,  10,  false⟩ -- denied (path traversal!)
    let c3  : ToolCall := ⟨7, false, true,  false, 50,  false⟩ -- denied (destructive, no approval!)
    let c4  : ToolCall := ⟨7, false, true,  true,  200, false⟩ -- allowed (destructive + human approved!)
    let c5  : ToolCall := ⟨7, false, false, false, 10,  true⟩  -- trips kill-switch!
    let c6  : ToolCall := ⟨7, false, false, true,  10,  false⟩ -- denied (frozen after kill-switch!)
    let sf := execTrace pol s0 [c1, c2, c3, c4, c5, c6]
    (evalToolCall pol s0 c2).1 = Decision.deniedScope ∧
    (evalToolCall pol s0 c3).1 = Decision.deniedApproval ∧
    sf = { spentCents := 320, callCount := 2, halted := true } := by
  sorry

end Challenge
