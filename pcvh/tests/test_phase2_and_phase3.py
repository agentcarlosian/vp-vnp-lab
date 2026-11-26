"""End-to-end verification tests for PCVH Phase 2 (LSP, Falsifier, lean-orch) & Phase 3 (Autonomous Prover)."""

from __future__ import annotations

import pathlib
import sys
from typing import List, Tuple

import pytest

PKG_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from pcvh.agents.orchestrator import run_autonomous_prove_pipeline
from pcvh.agents.prover import ProofPromptContext
from pcvh.agents.retriever import build_premise_index_from_modules
from pcvh.config import load_spec_config
from pcvh.runtime.lean_diagnostics import LeanLSPClient
from pcvh.tcb.manifest import pin_tcb_manifest
from tests._lean_env import LAKE_EXE_NAME, detect_lean_bin

BLUEPRINT3_DIR = PKG_ROOT / "blueprints" / "03_ssa_peephole_opt"
BLUEPRINT4_DIR = PKG_ROOT / "blueprints" / "04_double_entry_ledger"
LOCAL_LEAN_BIN = detect_lean_bin(BLUEPRINT3_DIR)


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4.33.1 toolchain missing")
def test_phase2_live_lean_lsp_plain_goal_extraction(tmp_path: pathlib.Path):
    """Query live Lean 4.33.1 headless LSP (`$/lean/plainGoal`) on a real `sorry` tactic."""
    proj = tmp_path / "lsp_probe"
    (proj / "Specs").mkdir(parents=True)
    (proj / "lean-toolchain").write_text("leanprover/lean4:v4.33.1\n", encoding="utf-8")
    (proj / "lakefile.toml").write_text(
        'name = "lsp_probe"\ndefaultTargets = ["Specs"]\n\n[[lean_lib]]\nname = "Specs"\n',
        encoding="utf-8",
    )
    target = proj / "Specs" / "Demo.lean"
    src = (
        "theorem add_zero_right (n : Nat) : n + 0 = n := by\n"
        "  sorry\n"
    )
    target.write_text(src, encoding="utf-8")

    with LeanLSPClient(proj, lean_bin=LOCAL_LEAN_BIN) as lsp:
        goals, rendered = lsp.get_plain_goal(target, line_0idx=1, col_0idx=2, text=src)
    assert len(goals) >= 1
    assert any("n + 0 = n" in g for g in goals), f"Unexpected LSP goals: {goals}"
    assert rendered is not None


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4.33.1 toolchain missing")
def test_phase2_falsifier_refutes_buggy_spec_before_proving(tmp_path: pathlib.Path):
    """Stage 2 MUST catch a false invariant in seconds and abort BEFORE spending any prover rounds."""
    proj = tmp_path / "buggy_vault"
    (proj / "Specs").mkdir(parents=True)
    (proj / "lean-toolchain").write_text("leanprover/lean4:v4.33.1\n", encoding="utf-8")
    (proj / "lakefile.toml").write_text(
        'name = "buggy_vault"\ndefaultTargets = ["Specs.Challenge", "Solution"]\n\n'
        '[[lean_lib]]\nname = "Specs"\n\n[[lean_lib]]\nname = "Solution"\n',
        encoding="utf-8",
    )
    (proj / "pcvh.toml").write_text(
        '[spec]\n'
        'name = "buggy-vault"\n'
        'lean_toolchain = "leanprover/lean4:v4.33.1"\n'
        'statement = "Specs/Statement.lean"\n'
        'challenge = "Specs/Challenge.lean"\n'
        'challenge_module = "Specs.Challenge"\n'
        'solution_module = "Solution"\n'
        'require_nonvacuity_witness = true\n\n'
        '[falsification]\n'
        'enabled = true\n'
        'lean_samples = 32\n',
        encoding="utf-8",
    )
    # Buggy withdraw function: forgets to check `amt <= bal` (allows negative balance)!
    (proj / "Specs" / "Statement.lean").write_text(
        "namespace Vault\n"
        "def buggyWithdraw (bal amt : Int) : Int := bal - amt\n"
        "end Vault\n",
        encoding="utf-8",
    )
    # False invariant claiming balance stays >= 0 for all non-negative bal, amt!
    (proj / "Specs" / "Challenge.lean").write_text(
        "import Specs.Statement\n"
        "namespace Challenge\n"
        "open Vault\n"
        "theorem withdraw_stays_nonneg (bal amt : Int) (h1 : 0 ≤ bal) (h2 : 0 ≤ amt) :\n"
        "    0 ≤ buggyWithdraw bal amt := by sorry\n"
        "theorem vault_nonvacuous : buggyWithdraw 10 3 = 7 := by sorry\n"
        "end Challenge\n",
        encoding="utf-8",
    )

    cfg = load_spec_config(proj)
    pin_tcb_manifest(cfg, save_snapshot=True)
    res = run_autonomous_prove_pipeline(cfg, lean_bin=LOCAL_LEAN_BIN)

    assert res.status == "REFUTED_BY_FALSIFIER"
    assert res.falsification.status == "REFUTED"
    assert len(res.falsification.counterexamples) >= 1
    assert res.falsification.counterexamples[0].theorem == "withdraw_stays_nonneg"
    assert res.proof_results == []  # ZERO prover attempts wasted!


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4.33.1 toolchain missing")
def test_phase3_bm25_premise_retriever_reflects_real_lean_module(copy_blueprint):
    """Reflect real compiled `.olean` declarations and rank relevant premises with BM25."""
    # Ensure Statement.olean exists in Blueprint 4 via isolated build
    bp = copy_blueprint(BLUEPRINT4_DIR.name)
    from pcvh.tcb.palomar_gate import _run_with_transient_oom_retry
    import os
    env = dict(os.environ, PATH=str(LOCAL_LEAN_BIN) + os.pathsep + os.environ.get("PATH", ""))
    _run_with_transient_oom_retry(
        [str(LOCAL_LEAN_BIN / LAKE_EXE_NAME), "build", "Specs.Ledger.Statement"],
        cwd=bp,
        env=env,
    )

    idx = build_premise_index_from_modules(
        bp,
        ["Specs.Ledger.Statement"],
        lean_bin=LOCAL_LEAN_BIN,
    )
    assert len(idx) >= 12
    hits = idx.search("totalBalance (applyDelta balances fromAcct delta) = totalBalance balances", top_k=5)
    hit_names = [h.entry.short_name for h in hits]
    assert "totalBalance" in hit_names
    assert "applyDelta" in hit_names


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4.33.1 toolchain missing")
def test_phase3_autonomous_prove_blueprint3_compiler_pass_e2e(copy_blueprint):
    """End-to-end 7-stage autonomous `pcvh prove` on UNSOLVED Blueprint 3 (AST Peephole Optimizer)!"""
    bp = copy_blueprint(BLUEPRINT3_DIR.name)
    # Clean any previously synthesized Solution files so this proves 100% from scratch!
    sol_file = bp / "Solution.lean"
    sol_dir = bp / "Solution"
    if sol_file.exists():
        sol_file.unlink()
    if sol_dir.exists():
        import shutil
        shutil.rmtree(sol_dir)

    cfg = load_spec_config(bp)
    pin_tcb_manifest(cfg, save_snapshot=True)

    res = run_autonomous_prove_pipeline(
        cfg,
        lean_bin=LOCAL_LEAN_BIN,
        attestation_out=bp / "proof-attestation.json",
    )
    assert res.status == "VERIFIED", (
        f"Autonomous prove failed: status={res.status}\n"
        f"proofs={[(p.theorem_name, p.proved, p.tier_used, p.last_errors[:1]) for p in res.proof_results]}\n"
        f"gate={res.gate_result.failure_reasons if res.gate_result else None}"
    )
    assert res.falsification.status == "PASSED"
    assert len(res.proof_results) == 6
    assert all(p.proved for p in res.proof_results)
    assert res.build_and_shake is not None and res.build_and_shake.build_ok
    assert res.gate_result is not None and res.gate_result.verdict == "VERIFIED"
    assert set(res.gate_result.verified_theorems) == {
        "iropt_spec_nonvacuous",
        "optPass_nonexpanding",
        "optPass_sound",
        "simpAdd_sound",
        "simpMul_sound",
        "simpSub_sound",
    }
    assert set(res.gate_result.axioms_used).issubset({"propext", "Classical.choice", "Quot.sound"})


class _ScriptedRepairLLMBackend:
    """Deterministic multi-round test double exercising Tier-3 LSP goal + BM25 + anti-cheat + error repair."""

    def __init__(self) -> None:
        self.calls: List[ProofPromptContext] = []

    def propose_tactic_proof(self, ctx: ProofPromptContext) -> Tuple[str, float]:
        self.calls.append(ctx)
        if ctx.theorem_name == "escrow_nonvacuous":
            return "unfold release; decide", 0.01
        # Round 1: try sneaky `sorry` -> MUST be blocked immediately by anti-cheat!
        if ctx.round_idx == 1:
            return "sorry", 0.01
        # Round 2: try broken tactic -> Lean 4 JSON error fed into Round 3!
        if ctx.round_idx == 2:
            return "exact nonexistent_theorem_hallucination", 0.01
        # Round 3: repaired valid proof using diagnostic feedback!
        return "unfold release; split <;> omega", 0.01


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4.33.1 toolchain missing")
def test_phase3_tier3_llm_repair_loop_with_live_lsp_and_bm25(tmp_path: pathlib.Path):
    """Verify Tier-3 escalates with live LSP goals + BM25 premises, blocks LLM `sorry`, repairs errors, and passes Palomar Gate."""
    proj = tmp_path / "escrow_llm"
    (proj / "Specs").mkdir(parents=True)
    (proj / "lean-toolchain").write_text("leanprover/lean4:v4.33.1\n", encoding="utf-8")
    (proj / "lakefile.toml").write_text(
        'name = "escrow_llm"\ndefaultTargets = ["Specs.Challenge", "Solution"]\n\n'
        '[[lean_lib]]\nname = "Specs"\n\n[[lean_lib]]\nname = "Solution"\n',
        encoding="utf-8",
    )
    (proj / "pcvh.toml").write_text(
        '[spec]\n'
        'name = "escrow-llm-repair"\n'
        'lean_toolchain = "leanprover/lean4:v4.33.1"\n'
        'statement = "Specs/Statement.lean"\n'
        'challenge = "Specs/Challenge.lean"\n'
        'challenge_module = "Specs.Challenge"\n'
        'solution_module = "Solution"\n'
        'require_nonvacuity_witness = true\n\n'
        '[falsification]\n'
        'enabled = true\n'
        'lean_samples = 24\n\n'
        '[agent_loop]\n'
        'max_rounds_per_lemma = 5\n'
        'max_token_budget_usd = 1.0\n',
        encoding="utf-8",
    )
    (proj / "Specs" / "Statement.lean").write_text(
        "namespace Escrow\n"
        "def release (bal req : Int) : Int := if req ≤ bal then bal - req else bal\n"
        "end Escrow\n",
        encoding="utf-8",
    )
    (proj / "Specs" / "Challenge.lean").write_text(
        "import Specs.Statement\n"
        "namespace Challenge\n"
        "open Escrow\n"
        "theorem release_stays_nonneg (bal req : Int) (hb : 0 ≤ bal) (hr : 0 ≤ req) :\n"
        "    0 ≤ release bal req := by sorry\n"
        "theorem escrow_nonvacuous : release 100 40 = 60 := by sorry\n"
        "end Challenge\n",
        encoding="utf-8",
    )

    cfg = load_spec_config(proj)
    pin_tcb_manifest(cfg, save_snapshot=True)
    llm = _ScriptedRepairLLMBackend()

    res = run_autonomous_prove_pipeline(
        cfg,
        lean_bin=LOCAL_LEAN_BIN,
        llm_backend=llm,
        skip_symbolic_tiers=True,  # Force Tier-3 LLM loop end-to-end!
    )

    assert res.status == "VERIFIED", f"Tier-3 LLM repair failed: {res.to_dict()}"
    # Verify multi-round repair + live LSP goals + BM25 premises + anti-cheat rejection
    rel_calls = [c for c in llm.calls if c.theorem_name == "release_stays_nonneg"]
    assert len(rel_calls) == 3
    assert any("release" in g for g in rel_calls[0].live_lsp_goals)
    assert "Escrow.release" in rel_calls[0].retrieved_premises_text
    assert any("banned_sorry" in e for e in rel_calls[1].previous_errors)
    assert any("unknown identifier" in e.lower() or "nonexistent_theorem_hallucination" in e for e in rel_calls[2].previous_errors)
    assert res.gate_result is not None and res.gate_result.verdict == "VERIFIED"
