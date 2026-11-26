# `vp-vnp-lab`

**[Live Specifications Monograph (GitHub Pages)](https://agentcarlosian.github.io/vp-vnp-lab/)** · **[40-Invariant Benchmark Report](https://agentcarlosian.github.io/vp-vnp-lab/eval/)** · **[Full Technical Lab Report](./docs/vp_vnp_lab_report.md)**

Independent Lean 4.33.1 verification, formalization of **Remark N.6**, computational math experiments inspired by Anthropic's *"VP ≠ VNP Over Every Field"* ([`anthropics/formal-math`](https://github.com/anthropics/formal-math)), and **three reusable engineering tools** built directly from the lab:

1. **[`pcvh/`](./pcvh/)** — **Agentic Proof-Carrying Verification Harness**: zero-trust Palomar-style Spec → Proof agent loop for real engineering invariants (8 verified blueprints spanning DeFi vaults/AMMs, BFT consensus, SSA compiler passes, double-entry ledgers, CAT(0) convex proof certificates, TypeScript AI agent guardrails, Rust limit order books, and ZK gadgets + WireGuard anti-replay windows).
2. **[`lean-build-orchestrator/`](./lean-build-orchestrator/)** — **Windows / Low-RAM Lean 4 Build Orchestrator & Import Minimizer (`lean-orch`)**: Win32 `GetPerformanceInfo` commit-charge scheduler + `lake shake` import minimizer solving the Windows `import Mathlib` pagefile bottleneck.
3. **[`quantum-cat0-checker/`](./quantum-cat0-checker/)** — **Quantum-Network Entanglement Capacity & CAT(0) Feasibility Checker (`qcat0`)**: exact DCP-convex CVXPY SOCP/SDP solver applying Theorem C.1's Berg–Nikolaev CAT(0) inequalities to multi-party quantum network topologies.

---

## What the evidence covers

| Result | Check or evidence |
| --- | --- |
| Upstream VP–VNP | The [lab report](docs/vp_vnp_lab_report.md) records a local 323-module build. That is not a CI result. |
| Remark N.6 | [Reproduce the conditional bridge](remark-n6-lean/README.md). The full, separately documented check applies the bridge to the upstream `Solution` theorem; the report records that check locally. |
| PCVH blueprints | [Blueprint CI](.github/workflows/ci.yml) checks eight projects. The separate main-branch dual-kernel job checks Lean and NanoDA, signs the reports and publishes the [verification bundle](pcvh/README.md#verify-a-ci-evidence-bundle). |
| Eval-40 | [Published fixture snapshot](pcvh/eval_results_40.json): 32 of 32 sound fixtures verified and 8 of 8 seeded defects detected. This is not a conformance or dual-kernel run; false acceptance was not measured. |
| lean-orch | [CI](.github/workflows/ci.yml) covers miniature Lean builds, with a native Windows smoke job for commit telemetry. This is not a full Mathlib performance benchmark. |
| qcat0 | [Certificate checks](quantum-cat0-checker/README.md#interpreting-single-restriction-results) distinguish floating-point search, a rationally verified upper bound and a Lean inequality for integer edge variables under stated premises. |
| Research experiments | Six exploratory scripts in [`experiments/`](experiments/) (exp04–exp09); not part of blueprint or formal proof CI. |

## Repository Map

```text
vp-vnp-lab/
├── pcvh/                         # Proof-Carrying Verification Harness (Phases 1–6, 8 blueprints, 40-task eval, Web Studio)
│   ├── pcvh/                     #   tcb/ (Palomar + dual-kernel + Ed25519), adapters/, runtime/ (LSP), falsify/, agents/ (LLMs + tree search), ci/, eval/, studio/
│   ├── blueprints/               #   01..08 (Vault/AMM, BFT, IR Opt, Ledger, CAT(0), TS Agent Guard, Rust OrderBook, ZK+Replay)
│   ├── tests/                    #   Lean 4.33.1 integration, preflight policy and Docker verification tests
│   ├── pcvh/studio/              #   Packaged Studio UI, showcase and Eval-40 dashboard
│   └── eval_results_40.json      #   Machine-readable benchmark results
├── lean-build-orchestrator/      # Windows/low-RAM Lean 4 commit-aware scheduler & lake shake minimizer (`lean-orch`)
├── quantum-cat0-checker/         # CVXPY SOCP/SDP CAT(0) quantum entanglement capacity solver (`qcat0`)
├── remark-n6-lean/               # Standalone Lean 4.33.1 Remark N.6 formalization + axiom verification scripts
├── experiments/                  # Executable Python symbolic/numerical math scripts (exp04–exp09)
├── scripts/                      # Topological batched Lake builder (build_lean_batched.py)
├── docs/                         # Full technical lab report (vp_vnp_lab_report.md)
├── plans/                        # Interactive HTML architecture plan (proof_carrying_verification_harness_plan.html)
└── .github/workflows/ci.yml      # Tool CI, including eight PCVH blueprints and the Windows smoke job
```

---

## Quick Start

Run the install commands from the repository root in an activated Python 3.11+ virtual environment. For example, create one with `python -m venv .venv`, then activate it with `source .venv/bin/activate` on Bash or `.venv\Scripts\Activate.ps1` in PowerShell.

### 1. Proof-Carrying Verification Harness (`pcvh`)

This local example runs code from the reviewed checkout. For someone else’s candidate, use the [isolated Docker workflow](pcvh/README.md#verifying-a-candidate-checkout) instead.

```bash
python -m pip install "./pcvh[dev]"
pcvh verify --trusted-local pcvh/blueprints/01_erc4626_vault
pcvh studio --trusted-local --root pcvh
```

Proof commands use Lean 4.33.1 (install via [elan](https://github.com/leanprover/elan)); the TypeScript and Rust blueprints additionally use Node.js 24 and Rust/Cargo respectively. The local Studio runs on loopback by default.

### 2. Lean build orchestrator (`lean-orch`)

```bash
python -m pip install "./lean-build-orchestrator[dev]"
lean-orch audit /path/to/lean-project
```

The audit is read-only. Building and applying import fixes require the project’s Lean/Lake toolchain. See the [full lean-orch quickstart](lean-build-orchestrator/README.md#quick-start).

### 3. Quantum-network CAT(0) capacity checker (`qcat0`)

```bash
python -m pip install "./quantum-cat0-checker[dev]"
qcat0 check C4_crossing
```

Lean is only needed to check an exported Lean certificate, not for this numerical check. See the [qcat0 quickstart](quantum-cat0-checker/README.md#quick-start).

### 4. Remark N.6 Lean 4 Formalization & Research Report
- See [`remark-n6-lean/README.md`](./remark-n6-lean/README.md) to reproduce `RemarkN6.lean` and `CheckFullVerification.lean` against `anthropics/formal-math/vp-vnp`.
- Read the full lab report in [`docs/vp_vnp_lab_report.md`](./docs/vp_vnp_lab_report.md) and the interactive PCVH architecture plan in [`plans/proof_carrying_verification_harness_plan.html`](./plans/proof_carrying_verification_harness_plan.html).

---

## Attribution & License

Licensed under the [Apache License 2.0](./LICENSE).

The Remark N.6 formalization (`remark-n6-lean/`) builds on `Statement.lean` and `Solution.lean` from [`anthropics/formal-math`](https://github.com/anthropics/formal-math) (`vp-vnp`, Apache-2.0), and the zero-trust verification architecture of `pcvh/` is inspired by the Palomar comparator workflow introduced there.
