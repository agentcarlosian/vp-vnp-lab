// Production TypeScript AI Agent Capability & Spending Guardrail Proxy (Blueprint 06)

export interface Policy {
  maxBudgetCents: bigint;
  maxCalls: bigint;
  allowedScopeId: bigint;
}

export interface GuardState {
  spentCents: bigint;
  callCount: bigint;
  halted: boolean;
}

export interface ToolCall {
  scopeId: bigint;
  isPathTraversal: boolean;
  isDestructive: boolean;
  hasHumanApproval: boolean;
  costCents: bigint;
  tripKillSwitch: boolean;
}

export const DecisionCode = {
  Allowed: 0,
  DeniedHalted: 1,
  DeniedScope: 2,
  DeniedApproval: 3,
  DeniedRateLimit: 4,
  DeniedBudget: 5,
} as const;

export type DecisionVal = (typeof DecisionCode)[keyof typeof DecisionCode];

export function evalToolCall(
  pol: Policy,
  st: GuardState,
  call: ToolCall
): { decision: DecisionVal; nextState: GuardState } {
  if (st.halted) {
    return { decision: DecisionCode.DeniedHalted, nextState: st };
  }
  if (call.tripKillSwitch) {
    return {
      decision: DecisionCode.DeniedHalted,
      nextState: { ...st, halted: true },
    };
  }
  if (call.isPathTraversal || call.scopeId !== pol.allowedScopeId) {
    return { decision: DecisionCode.DeniedScope, nextState: st };
  }
  if (call.isDestructive && !call.hasHumanApproval) {
    return { decision: DecisionCode.DeniedApproval, nextState: st };
  }
  if (pol.maxCalls <= st.callCount) {
    return { decision: DecisionCode.DeniedRateLimit, nextState: st };
  }
  if (pol.maxBudgetCents < st.spentCents + call.costCents) {
    return { decision: DecisionCode.DeniedBudget, nextState: st };
  }
  return {
    decision: DecisionCode.Allowed,
    nextState: {
      spentCents: st.spentCents + call.costCents,
      callCount: st.callCount + 1n,
      halted: st.halted,
    },
  };
}
