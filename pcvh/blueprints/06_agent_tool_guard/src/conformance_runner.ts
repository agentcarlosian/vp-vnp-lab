import { evalToolCall, type GuardState, type Policy, type ToolCall } from "./agent_guard.ts";

const traces: number = Number(process.argv[2] ?? "1000");
let rngState: bigint = BigInt(process.argv[3] ?? "606");

function nextRand(): bigint {
  rngState = (rngState * 6364136223846793005n + 1442695040888963407n) & ((1n << 64n) - 1n);
  return rngState >> 16n;
}

const rows: string[] = [];
for (let t = 0; t < traces; t++) {
  const pol: Policy = {
    maxBudgetCents: (nextRand() % 2000n) + 100n,
    maxCalls: (nextRand() % 10n) + 1n,
    allowedScopeId: (nextRand() % 5n) + 1n,
  };
  let st: GuardState = { spentCents: 0n, callCount: 0n, halted: false };

  const callStrs: string[] = [];
  const decStrs: string[] = [];

  for (let s = 0; s < 12; s++) {
    const scopeId = nextRand() % 100n < 75n ? pol.allowedScopeId : (nextRand() % 8n);
    const isPathTraversal = (nextRand() % 100n) < 15n;
    const isDestructive = (nextRand() % 100n) < 30n;
    const hasHumanApproval = (nextRand() % 100n) < 50n;
    const costCents = nextRand() % 450n;
    const tripKillSwitch = (nextRand() % 100n) < 8n;

    const call: ToolCall = {
      scopeId,
      isPathTraversal,
      isDestructive,
      hasHumanApproval,
      costCents,
      tripKillSwitch,
    };
    const { decision, nextState } = evalToolCall(pol, st, call);
    st = nextState;

    if (st.spentCents > pol.maxBudgetCents || st.callCount > pol.maxCalls) {
      throw new Error("TypeScript guardrail violated budget or rate cap!");
    }

    callStrs.push(
      `${scopeId}:${isPathTraversal ? 1 : 0}:${isDestructive ? 1 : 0}:${hasHumanApproval ? 1 : 0}:${costCents}:${tripKillSwitch ? 1 : 0}`
    );
    decStrs.push(String(decision));
  }

  rows.push(
    `${pol.maxBudgetCents}|${pol.maxCalls}|${pol.allowedScopeId}|` +
      `${callStrs.join(",")}|${decStrs.join(",")}|${st.spentCents}|${st.callCount}|${st.halted ? 1 : 0}`
  );
}

process.stdout.write(rows.join("\n") + "\n");
