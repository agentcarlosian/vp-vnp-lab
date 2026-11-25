# `vp-vnp-lab`

**[Live Specifications Monograph (GitHub Pages)](https://agentcarlosian.github.io/vp-vnp-lab/)** · **[40-Invariant Benchmark Report](https://agentcarlosian.github.io/vp-vnp-lab/eval/)** · **[Full Technical Lab Report](./docs/vp_vnp_lab_report.md)**

Independent Lean 4.33.1 verification, formalization of **Remark N.6**, computational math experiments inspired by Anthropic's *"VP ≠ VNP Over Every Field"* ([`anthropics/formal-math`](https://github.com/anthropics/formal-math)), and **three reusable engineering tools** built directly from the lab:

1. **[`pcvh/`](./pcvh/)** — **Agentic Proof-Carrying Verification Harness**: zero-trust Palomar-style Spec → Proof agent loop for real engineering invariants (8 verified blueprints spanning DeFi vaults/AMMs, BFT consensus, SSA compiler passes, double-entry ledgers, CAT(0) convex proof certificates, TypeScript AI agent guardrails, Rust limit order books, and ZK gadgets + WireGuard anti-replay windows).
2. **[`lean-build-orchestrator/`](./lean-build-orchestrator/)** — **Windows / Low-RAM Lean 4 Build Orchestrator & Import Minimizer (`lean-orch`)**: Win32 `GetPerformanceInfo` commit-charge scheduler + `lake shake` import minimizer solving the Windows `import Mathlib` pagefile bottleneck.
3. **[`quantum-cat0-checker/`](./quantum-cat0-checker/)** — **Quantum-Network Entanglement Capacity & CAT(0) Feasibility Checker (`qcat0`)**: exact DCP-convex CVXPY SOCP/SDP solver applying Theorem C.1's Berg–Nikolaev CAT(0) inequalities to multi-party quantum network topologies.

---

## Headline Verification Results

| Component | Result | Details |
| --- | --- | --- |
| **`vp-vnp` full local build + Remark N.6** | **323 / 323 modules + `remarkN6_unconditional` VERIFIED** | All 5 headline `Solution.*` theorems + our 891-line division-free Samuelson–Berkowitz formalization [`remark-n6-lean/RemarkN6.lean`](./remark-n6-lean/RemarkN6.lean) verified in Lean 4.33.1 on `[propext, Classical.choice, Quot.sound]` only (0 `sorry`, 0 warnings). |
| **`pcvh` (Phases 1–6 + 8 Blueprints)** | **39 / 39 tests passing** | 12/12 red-team cheats + guillemet/metaprogramming anti-cheat, **8/8 blueprints (48 theorems, 6,000 live Python/Rust/TS traces)** Palomar-verified, Rust/TypeScript/Solidity/Python adapters (`pcvh init`), Anthropic/OpenAI/Ollama LLMs + best-first LSP tree search + parallel proving, `lean4export`+`nanoda` dual-kernel CI & Ed25519 DSSE signing, interactive `pcvh studio` Web UI, 40/40 live eval benchmark. |
| **`lean-build-orchestrator`** | **8 / 8 tests passing** | Live Lean 4.33.1 build + native `lake shake --fix` + automatic `.olean` environment fallback + rollback safety. |
| **`quantum-cat0-checker`** | **13 / 13 tests passing** | Exact $\sqrt{2}\times$ on $C_4$, $\sqrt{3}\times$ on $Q_3$, strict 3-way cone separations on $K_{2,3}$ & $3\times 3$ planar grid, permutation-invariant GHZ bounds, and `qcat0 certify` exact `Fraction`-verified Farkas dual certificates + standalone Lean 4 proof export. |
| **Research experiments (`exp04`–`exp09`)** | **6 / 6 scripts passing** | Meixner–Frobenius crossing identity, Prop. E.1/M.2 `#SAT -> PERM/HC` compilers, Grassmannian Möbius contraction bound on $\mathrm{Mat}_\mu(\mathbb{F}_2)$, flat-case hub optimizer, $\mathrm{SL}_3(\mathbb{F}_2[s]/(s^2))$ coset tower, PIT & CAT(0) calculations. |

---

## Repository Map

```text
vp-vnp-lab/
├── pcvh/                         # Proof-Carrying Verification Harness (Phases 1–6, 8 blueprints, 40-task eval, Web Studio)
│   ├── pcvh/                     #   tcb/ (Palomar + dual-kernel + Ed25519), adapters/, runtime/ (LSP), falsify/, agents/ (LLMs + tree search), ci/, eval/, studio/
│   ├── blueprints/               #   01..08 (Vault/AMM, BFT, IR Opt, Ledger, CAT(0), TS Agent Guard, Rust OrderBook, ZK+Replay)
│   ├── tests/                    #   39 live Lean 4.33.1 tests (12 red-team attacks, Phase 2–6, Rust/TS/Solidity adapters, Web Studio)
│   ├── blueprints_showcase.html  #   Editorial 8-blueprint specification monograph
│   ├── eval_dashboard.html       #   Interactive 40-invariant benchmark dashboard
│   └── eval_results_40.json      #   Machine-readable benchmark results
├── lean-build-orchestrator/      # Windows/low-RAM Lean 4 commit-aware scheduler & lake shake minimizer (`lean-orch`)
├── quantum-cat0-checker/         # CVXPY SOCP/SDP CAT(0) quantum entanglement capacity solver (`qcat0`)
├── remark-n6-lean/               # Standalone Lean 4.33.1 Remark N.6 formalization + axiom verification scripts
├── experiments/                  # Executable Python symbolic/numerical math scripts (exp04–exp09)
├── scripts/                      # Topological batched Lake builder (build_lean_batched.py)
├── docs/                         # Full technical lab report (vp_vnp_lab_report.md)
├── plans/                        # Interactive HTML architecture plan (proof_carrying_verification_harness_plan.html)
└── .github/workflows/ci.yml      # Unified GitHub Actions CI across all tools and 5 PCVH blueprints
```

---

## Quick Start

### Prerequisites
- **Python 3.11+** (tested on Python 3.13) with `pytest`, `numpy`, `scipy`, `cvxpy`, `networkx`, `sympy`, `psutil`
- **Lean 4.33.1** via [`elan`](https://github.com/leanprover/elan) (auto-detected from `PATH`, `ELAN_HOME`, `~/.elan`, or a local `.elan/` folder)

### 1. Proof-Carrying Verification Harness (`pcvh`)
```bash
cd pcvh
python -m pcvh verify blueprints/01_erc4626_vault
python -m pcvh verify blueprints/02_bft_consensus
python -m pcvh prove  blueprints/03_ssa_peephole_opt
python -m pcvh verify blueprints/04_double_entry_ledger
python -m pcvh cert-cat0 blueprints/05_cat0_certificate
python -m pcvh verify blueprints/06_agent_tool_guard
python -m pcvh verify blueprints/07_orderbook_matching
python -m pcvh verify blueprints/08_zk_and_replay_window
python -m pcvh studio --root .
python -m pytest -v tests/
```

### 2. Lean 4 Commit-Aware Build Orchestrator (`lean-orch`)
```bash
cd lean-build-orchestrator
python -m lean_orch audit /path/to/lean-project
python -m lean_orch build /path/to/lean-project --reserve-gb 3.0
python -m lean_orch shake /path/to/lean-project --fix
python -m pytest -v tests/
```

### 3. Quantum-Network CAT(0) Capacity Checker (`qcat0`)
```bash
cd quantum-cat0-checker
python -m quantum_cat0 list
python -m quantum_cat0 check K23_bipartite
python -m quantum_cat0 certify hypercube_Q3 --lean-out Q3Cert.lean
python -m quantum_cat0 benchmark
python -m pytest -v tests/
```

### 4. Remark N.6 Lean 4 Formalization & Research Report
- See [`remark-n6-lean/README.md`](./remark-n6-lean/README.md) to reproduce `RemarkN6.lean` and `CheckFullVerification.lean` against `anthropics/formal-math/vp-vnp`.
- Read the full lab report in [`docs/vp_vnp_lab_report.md`](./docs/vp_vnp_lab_report.md) and the interactive PCVH architecture plan in [`plans/proof_carrying_verification_harness_plan.html`](./plans/proof_carrying_verification_harness_plan.html).

---

## Attribution & License

Licensed under the [Apache License 2.0](./LICENSE).

The Remark N.6 formalization (`remark-n6-lean/`) builds on `Statement.lean` and `Solution.lean` from [`anthropics/formal-math`](https://github.com/anthropics/formal-math) (`vp-vnp`, Apache-2.0), and the zero-trust verification architecture of `pcvh/` is inspired by the Palomar comparator workflow introduced there.
