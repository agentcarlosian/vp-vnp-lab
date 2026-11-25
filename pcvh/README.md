# `pcvh` — Agentic Proof-Carrying Verification Harness (Complete Phases 1–6)

## Verifying a candidate checkout

Use a trusted installation of PCVH on the host. Build the verifier image from a reviewed copy of this directory. Run `pcvh pin` on a separate, reviewed reference project and record its full SHA-256 digest before accepting a candidate. Copy that v2 lock to the candidate as part of the public specification. The digest covers the verification configuration, Lean specification, build configuration and standard conformance bridge. Include additional trusted oracle scripts and imported specification files in `spec.extra_tcb_files`. Python callers can use `pcvh.tcb.isolated.verify_isolated` with the same image ID and digest.

```sh
docker build -f Dockerfile.verifier -t pcvh-verifier .
reviewed_digest=$(python -m pcvh pin /path/to/reviewed-reference --json | python -c 'import json,sys; print(json.load(sys.stdin)["spec_bundle_sha256"])')
image=$(docker image inspect pcvh-verifier --format '{{.Id}}')
python -m pcvh verify /path/to/candidate --sandbox-image "$image" --expected-spec-sha256 "$reviewed_digest" --json
```

Supply a dedicated candidate source directory. The Linux worker receives read-only inputs, temporary build space, a fixed image toolchain and no network. Keep private material outside that directory. Save a report with `--attestation` to a verifier-owned path outside the candidate. An image for a project requiring a second kernel must also contain its configured independent verifier tools. The standard image includes Lean, Python, Node and Rust.

`--trusted-local` runs native programs with your account's permissions. Use it for your own reviewed projects. Studio, proving, incremental repair and scaffolding are local authoring workflows for trusted workspaces. Existing v1 projects need a new pin made from reviewed sources. Historical attestations retain the digest from their original run.


Zero-trust Palomar-style Spec → Proof agentic verification harness inspired by `anthropics/formal-math/vp-vnp`.

## All 6 Phases Completed & Verified (39 / 39 Live Lean 4.33.1 Tests Passing)

### Phase 1 — Zero-Trust Palomar Verification Gate (`pcvh/tcb/`)
- [manifest.py](pcvh/tcb/manifest.py): SHA-256 TCB pinning (`spec.lock.json`) and immutable overlay workspace construction.
- [static_audit.py](pcvh/tcb/static_audit.py): Comment-and-string-aware scanner banning `sorry`, `admit`, custom `axiom`, `native_decide`, `unsafe`, `implemented_by`, `extern`, `ofReduceBool`/`ofReduceNat`, `addDecl`/`setEnv`, `debug.skipKernelTC`, and umbrella `import Mathlib`.
- [palomar_gate.py](pcvh/tcb/palomar_gate.py): Isolated Lean 4.33.1 build + `Meta.isDefEq` theorem type comparator + `Lean.collectAxioms` allowlist + mandatory non-vacuity check + transient Windows commit-retry + signed `proof-attestation.json`.
- **12-Attack Red-Team Suite** ([tests/test_palomar_redteam.py](tests/test_palomar_redteam.py)): 12 / 12 cheating proofs deterministically rejected.

### Phase 2 — Runtime Bridge, Headless LSP & Stage-2 Falsification (`pcvh/runtime/`, `pcvh/falsify/`)
- [lean_diagnostics.py](pcvh/runtime/lean_diagnostics.py): Structured `lean --json` diagnostics + live JSON-RPC 2.0 `LeanLSPClient` (`$/lean/plainGoal`).
- [build_bridge.py](pcvh/runtime/build_bridge.py): Direct integration with `lean-build-orchestrator` (`lean-orch`) + Stage-6 `lake shake`.
- [falsifier.py](pcvh/falsify/falsifier.py): Fast `for`-loop Lean 4 `#eval` bounded refuter + external oracle hook + non-vacuity guard.

### Phase 3 — Autonomous Spec → Proof Synthesis Loop (`pcvh/agents/`)
- [retriever.py](pcvh/agents/retriever.py): Lean 4 `.olean` reflection + BM25 premise retriever.
- [planner.py](pcvh/agents/planner.py): Call-graph-ordered Lemma DAG planner (`Solution/Lem_*.lean`).
- [prover.py](pcvh/agents/prover.py): Deterministic tactic escalation (Tiers 0–2) + Tier-3 pluggable `LLMBackend` repair loop (`OpenAICompatibleLLMBackend`).
- [orchestrator.py](pcvh/agents/orchestrator.py): Full 7-stage `pcvh prove` controller.

### Phase 4 — Eight Verified Production Engineering Blueprints (`blueprints/`)
1. **Blueprint 1 (`blueprints/01_erc4626_vault/`)** — ERC-4626 Share Vault + Uniswap v2 AMM (6 theorems Palomar `VERIFIED` + `1000/1000` differential traces).
2. **Blueprint 2 (`blueprints/02_bft_consensus/`)** — BFT Quorum-Intersection Consensus (`3f < n`) + Merkle Soundness/Completeness (5 theorems Palomar `VERIFIED` + `500/500` differential traces).
3. **Blueprint 3 (`blueprints/03_ssa_peephole_opt/`)** — Arithmetic IR Peephole Optimizer (6 theorems **autonomously synthesized from scratch** by `pcvh prove`, Palomar `VERIFIED` + `500/500` AST differential traces).
4. **Blueprint 4 (`blueprints/04_double_entry_ledger/`)** — Double-Entry Idempotent Payment Ledger (6 theorems Palomar `VERIFIED` + `1000/1000` differential traces).
5. **Blueprint 5 (`blueprints/05_cat0_certificate/`)** — Primal-Dual CVXPY CAT(0) SOCP → Lean 4 Proof Certificate (4 theorems Palomar `VERIFIED`).
6. **Blueprint 6 (`blueprints/06_agent_tool_guard/`)** — AI Agent Capability, Scope, Human-Approval & Budget Guardrail Proxy against **TypeScript (`src/agent_guard.ts`)** (7 theorems Palomar `VERIFIED` + `1000/1000` 12-step Node.js TS traces).
7. **Blueprint 7 (`blueprints/07_orderbook_matching/`)** — Price-Time Priority Limit Order Book & Cross-Margin Engine against **Rust (`Cargo.toml` + `src/lib.rs`)** (6 theorems Palomar `VERIFIED` + `1000/1000` `cargo test`/`cargo run` traces).
8. **Blueprint 8 (`blueprints/08_zk_and_replay_window/`)** — R1CS/Plonkish Zero-Knowledge Range/MUX Gadgets + 64-Packet WireGuard Anti-Replay Window (8 theorems Palomar `VERIFIED` + `1000/1000` 64-bit bitmask traces).

### Phase 5 — CI/CD Matrix, PR Diff-Aware Re-Proving & 40-Invariant Eval Benchmark (`pcvh/ci/`, `pcvh/eval/`)
- [diff_reprove.py](pcvh/ci/diff_reprove.py): Transitive Statement-def + Challenge-signature hashing; re-proves only invalidated/new lemmas (`75%` cache hit verified).
- [../.github/workflows/ci.yml](../.github/workflows/ci.yml): 5-blueprint GitHub Actions verification matrix + PR summary badges + red-team CI job + independent dual-kernel `nanoda` job.
- [benchmark_40.py](pcvh/eval/benchmark_40.py): Live 40-invariant Lean 4.33.1 benchmark (**32/32 = 100%** sound invariants auto-proved & Palomar verified, **8/8 = 100%** buggy specs caught by Stage 2, **0%** false acceptance, `33.5s` total) emitting [eval_results_40.json](eval_results_40.json) and interactive [eval_dashboard.html](eval_dashboard.html).

### Phase 6 — Multi-Language Adapters, Tree-Search Prover, Dual-Kernel/Ed25519 Hardening & Web Studio
- **Multi-Language Target Adapters & `pcvh init`** ([adapters/scaffolder.py](pcvh/adapters/scaffolder.py)): Scaffolds pinned Lean 4 specs + production implementations + differential conformance bridges for **Rust (`cargo test` + trace binary)**, **TypeScript (Node.js native TS / `tsx`)**, **Solidity/Foundry (`forge test` + uint256 bridge)**, and **Python** across `ratelimit`, `vault`, and `ledger` templates.
- **Harder Autonomous Proof Synthesis** ([agents/llm_providers.py](pcvh/agents/llm_providers.py), [agents/tree_search.py](pcvh/agents/tree_search.py), [agents/orchestrator.py](pcvh/agents/orchestrator.py)): Native **Anthropic**, **OpenAI**, and **local Ollama** LLM backends, incremental `didChange` **best-first proof-tree search with live Lean 4 LSP goal-state backtracking**, and **`lean-orch` commit-charge-gated parallel topological wave proving**.
- **True Dual-Kernel & Cryptographic Attestation Hardening** ([tcb/dual_kernel.py](pcvh/tcb/dual_kernel.py), [tcb/crypto.py](pcvh/tcb/crypto.py)): Independent `lean4export` + `nanoda` second-kernel replay runner (`--require-dual-kernel` in Linux CI via [../scripts/setup_dual_kernel_ci.sh](../scripts/setup_dual_kernel_ci.sh)) and **Ed25519 DSSEv1** cryptographic signing/verification (`pcvh keygen`, `pcvh sign`, `pcvh verify-sig`, `pcvh verify --sign-key`) + optional Sigstore `cosign` hook.
- **Interactive Local Web Studio (`pcvh studio`)** ([studio/server.py](pcvh/studio/server.py), [studio/ui.html](pcvh/studio/ui.html)): Zero-dependency local web app to browse blueprints, scaffold projects, trigger async `verify`/`prove`/`diff-reprove`/`falsify` jobs, click any Lean line for live **`$/lean/plainGoal`** infoview goals, and verify Ed25519 DSSE attestations.

## Quick Start

```bash
cd pcvh
# Scaffold a Rust, TypeScript, Solidity/Foundry, or Python project
python -m pcvh init my_rust_limiter --lang rust --template ratelimit
python -m pcvh prove my_rust_limiter --workers 2 --llm-provider auto

# Verify existing blueprints + cryptographic Ed25519 DSSE signing
python -m pcvh keygen --out-dir .keys
python -m pcvh verify --trusted-local blueprints/01_erc4626_vault --sign-key .keys/pcvh_signing.key.pem
python -m pcvh verify-sig blueprints/01_erc4626_vault/proof-attestation.json --pubkey .keys/pcvh_signing.pub.pem

# Launch interactive PCVH Local Web Studio (http://127.0.0.1:8765)
python -m pcvh studio --trusted-local --root .

# Run full 36-test live Lean 4.33.1 test suite
python -m pytest -v tests/
```
