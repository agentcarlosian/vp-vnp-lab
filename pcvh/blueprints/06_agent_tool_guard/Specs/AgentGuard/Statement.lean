/-
  Blueprint 06 — Trusted Computing Base Specification (`Statement.lean`)
  AI Agent Capability, Workspace-Scope, Human-Approval & Spending-Budget Guardrail Proxy.
-/

namespace AgentGuard

structure Policy where
  maxBudgetCents : Nat
  maxCalls       : Nat
  allowedScopeId : Nat
  deriving Repr, DecidableEq

structure GuardState where
  spentCents : Nat
  callCount  : Nat
  halted     : Bool
  deriving Repr, DecidableEq

structure ToolCall where
  scopeId          : Nat
  isPathTraversal  : Bool
  isDestructive    : Bool
  hasHumanApproval : Bool
  costCents        : Nat
  tripKillSwitch   : Bool
  deriving Repr, DecidableEq

inductive Decision where
  | allowed
  | deniedHalted
  | deniedScope
  | deniedApproval
  | deniedRateLimit
  | deniedBudget
  deriving Repr, DecidableEq

def Decision.code : Decision → Nat
  | .allowed         => 0
  | .deniedHalted    => 1
  | .deniedScope     => 2
  | .deniedApproval  => 3
  | .deniedRateLimit => 4
  | .deniedBudget    => 5

/-- Deterministic zero-trust policy gate evaluated before every agent tool invocation. -/
def evalToolCall (pol : Policy) (st : GuardState) (call : ToolCall) : Decision × GuardState :=
  if st.halted then
    (.deniedHalted, st)
  else if call.tripKillSwitch then
    (.deniedHalted, { st with halted := true })
  else if call.isPathTraversal || (call.scopeId != pol.allowedScopeId) then
    (.deniedScope, st)
  else if call.isDestructive && !call.hasHumanApproval then
    (.deniedApproval, st)
  else if pol.maxCalls ≤ st.callCount then
    (.deniedRateLimit, st)
  else if pol.maxBudgetCents < st.spentCents + call.costCents then
    (.deniedBudget, st)
  else
    (.allowed, { st with spentCents := st.spentCents + call.costCents, callCount := st.callCount + 1 })

def stepState (pol : Policy) (st : GuardState) (call : ToolCall) : GuardState :=
  (evalToolCall pol st call).2

def execTrace (pol : Policy) (st : GuardState) : List ToolCall → GuardState
  | []          => st
  | call :: rem => execTrace pol (stepState pol st call) rem

end AgentGuard
