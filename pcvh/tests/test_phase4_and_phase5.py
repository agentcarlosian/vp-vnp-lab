"""End-to-end verification tests for PCVH Phase 4 (Blueprints 1–3 + Conformance) & Phase 5 (Diff-Reprove + 40-Task Eval)."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

PKG_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from pcvh.ci.diff_reprove import run_diff_aware_reprove
from pcvh.config import load_spec_config
from pcvh.eval.benchmark_40 import run_eval_benchmark_40
from pcvh.tcb.manifest import pin_tcb_manifest
from pcvh.tcb.palomar_gate import run_palomar_gate
from tests._lean_env import detect_lean_bin

LOCAL_LEAN_BIN = detect_lean_bin(PKG_ROOT)


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4.33.1 toolchain missing")
def test_phase4_blueprint1_erc4626_vault_amm_verified():
    bp = PKG_ROOT / "blueprints" / "01_erc4626_vault"
    cfg = load_spec_config(bp)
    pin_tcb_manifest(cfg, save_snapshot=True)
    res = run_palomar_gate(cfg, trusted_local=True, lean_bin=LOCAL_LEAN_BIN, run_conformance=True, attestation_out=bp / "proof-attestation.json")
    assert res.verdict == "VERIFIED", f"Blueprint 1 failed: {res.failure_reasons}"
    assert len(res.verified_theorems) == 6
    assert "1000/1000" in res.checks["differential_conformance"]


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4.33.1 toolchain missing")
def test_phase4_blueprint2_bft_consensus_merkle_verified():
    bp = PKG_ROOT / "blueprints" / "02_bft_consensus"
    cfg = load_spec_config(bp)
    pin_tcb_manifest(cfg, save_snapshot=True)
    res = run_palomar_gate(cfg, trusted_local=True, lean_bin=LOCAL_LEAN_BIN, run_conformance=True, attestation_out=bp / "proof-attestation.json")
    assert res.verdict == "VERIFIED", f"Blueprint 2 failed: {res.failure_reasons}"
    assert len(res.verified_theorems) == 5
    assert "500/500" in res.checks["differential_conformance"]


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4.33.1 toolchain missing")
def test_phase4_blueprint3_compiler_pass_with_ast_conformance_verified():
    bp = PKG_ROOT / "blueprints" / "03_ssa_peephole_opt"
    cfg = load_spec_config(bp)
    res = run_palomar_gate(cfg, trusted_local=True, lean_bin=LOCAL_LEAN_BIN, run_conformance=True, attestation_out=bp / "proof-attestation.json")
    assert res.verdict == "VERIFIED", f"Blueprint 3 failed: {res.failure_reasons}"
    assert len(res.verified_theorems) == 6
    assert "500/500" in res.checks["differential_conformance"]


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4.33.1 toolchain missing")
def test_phase5_diff_aware_incremental_reprove_preserves_unaffected_lemmas(tmp_path: pathlib.Path):
    """Simulate a PR adding a new invariant & editing one function: unaffected lemmas MUST hit cache!"""
    proj = tmp_path / "pr_diff_proj"
    (proj / "Specs").mkdir(parents=True)
    (proj / "lean-toolchain").write_text("leanprover/lean4:v4.33.1\n", encoding="utf-8")
    (proj / "lakefile.toml").write_text(
        'name = "pr_diff_proj"\ndefaultTargets = ["Specs.Challenge", "Solution"]\n\n'
        '[[lean_lib]]\nname = "Specs"\n\n[[lean_lib]]\nname = "Solution"\n',
        encoding="utf-8",
    )
    (proj / "pcvh.toml").write_text(
        '[spec]\nname = "pr-diff-test"\nlean_toolchain = "leanprover/lean4:v4.33.1"\n'
        'statement = "Specs/Statement.lean"\nchallenge = "Specs/Challenge.lean"\n'
        'challenge_module = "Specs.Challenge"\nsolution_module = "Solution"\n'
        'require_nonvacuity_witness = true\nnonvacuity_suffix = "nonvacuous"\n\n'
        '[falsification]\nenabled = true\nlean_samples = 16\n',
        encoding="utf-8",
    )
    (proj / "Specs" / "Statement.lean").write_text(
        "namespace RateLim\n"
        "def refill (cap cur add : Nat) : Nat := min cap (cur + add)\n"
        "def consume (cur cost : Nat) : Nat := if cost ≤ cur then cur - cost else cur\n"
        "end RateLim\n",
        encoding="utf-8",
    )
    (proj / "Specs" / "Challenge.lean").write_text(
        "import Specs.Statement\nnamespace Challenge\nopen RateLim\n"
        "theorem refill_bounded (cap cur add : Nat) : refill cap cur add ≤ cap := by sorry\n"
        "theorem consume_le (cur cost : Nat) : consume cur cost ≤ cur := by sorry\n"
        "theorem ratelim_nonvacuous : refill 10 8 5 = 10 ∧ consume 10 4 = 6 := by sorry\n"
        "end Challenge\n",
        encoding="utf-8",
    )

    # Initial PR run: proves all 3 theorems and writes `.pcvh_diff_cache.json`
    r1 = run_diff_aware_reprove(load_spec_config(proj), lean_bin=LOCAL_LEAN_BIN)
    assert r1.status == "VERIFIED", f"Initial run failed: {r1.to_dict()}"
    assert r1.cached_theorems == []
    assert len(r1.reproved_theorems) == 3

    # Simulated Developer PR: adds a brand-new `burstCap` function + 1 new invariant without touching `refill`/`consume`!
    (proj / "Specs" / "Statement.lean").write_text(
        "namespace RateLim\n"
        "def refill (cap cur add : Nat) : Nat := min cap (cur + add)\n"
        "def consume (cur cost : Nat) : Nat := if cost ≤ cur then cur - cost else cur\n"
        "def burstCap (cur bonus : Nat) : Nat := cur + bonus\n"
        "end RateLim\n",
        encoding="utf-8",
    )
    (proj / "Specs" / "Challenge.lean").write_text(
        "import Specs.Statement\nnamespace Challenge\nopen RateLim\n"
        "theorem refill_bounded (cap cur add : Nat) : refill cap cur add ≤ cap := by sorry\n"
        "theorem consume_le (cur cost : Nat) : consume cur cost ≤ cur := by sorry\n"
        "theorem burst_ge_cur (cur bonus : Nat) : cur ≤ burstCap cur bonus := by sorry\n"
        "theorem ratelim_nonvacuous : refill 10 8 5 = 10 ∧ consume 10 4 = 6 := by sorry\n"
        "end Challenge\n",
        encoding="utf-8",
    )

    # Second PR run: MUST reuse all 3 untouched theorems from cache and re-prove ONLY `burst_ge_cur`!
    r2 = run_diff_aware_reprove(load_spec_config(proj), lean_bin=LOCAL_LEAN_BIN)
    assert r2.status == "VERIFIED", f"Incremental PR run failed: {r2.to_dict()}"
    assert set(r2.cached_theorems) == {"refill_bounded", "consume_le", "ratelim_nonvacuous"}
    assert r2.reproved_theorems == ["burst_ge_cur"]
    assert r2.cache_hit_rate_pct == 75.0


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4.33.1 toolchain missing")
def test_phase5_40_invariant_engineering_eval_benchmark():
    """Run all 40 engineering benchmark tasks live in Lean 4.33.1 and emit JSON + HTML telemetry dashboard."""
    out_json = PKG_ROOT / "eval_results_40.json"
    out_html = PKG_ROOT / "eval_dashboard.html"
    summary = run_eval_benchmark_40(
        lean_bin=LOCAL_LEAN_BIN,
        out_json=out_json,
        out_html=out_html,
    )
    assert summary.total_tasks == 40
    assert summary.buggy_tasks == 8
    assert summary.sound_tasks == 32
    assert summary.buggy_caught_stage2 == 8, f"Missed buggy specs: {[r for r in summary.results if r.is_buggy and r.falsification != 'REFUTED']}"
    assert summary.sound_false_refutations == 0
    assert summary.sound_palomar_verified == 32, f"Unproved sound tasks: {[(r.task_id, r.tier_used) for r in summary.results if not r.is_buggy and not r.palomar_verified]}"
    assert summary.false_acceptance_count == 0
    assert out_json.exists() and out_html.exists()
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["sound_auto_prove_pct"] == 100.0
    assert data["falsification_recall_pct"] == 100.0
