"""End-to-end verification test for Blueprint 4 (Double-Entry Idempotent Payment Ledger)."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

PKG_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from pcvh.config import load_spec_config
from pcvh.tcb.manifest import pin_tcb_manifest
from pcvh.tcb.palomar_gate import run_palomar_gate
from tests._lean_env import detect_lean_bin

BLUEPRINT4_DIR = PKG_ROOT / "blueprints" / "04_double_entry_ledger"
LOCAL_LEAN_BIN = detect_lean_bin(BLUEPRINT4_DIR)


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4.33.1 toolchain missing")
def test_blueprint4_full_palomar_gate_and_differential_conformance():
    cfg = load_spec_config(BLUEPRINT4_DIR)
    pin_tcb_manifest(cfg, save_snapshot=True)
    att_path = BLUEPRINT4_DIR / "proof-attestation.json"

    res = run_palomar_gate(
        cfg,
        lean_bin=LOCAL_LEAN_BIN,
        run_conformance=True,
        attestation_out=att_path,
    )
    assert res.verdict == "VERIFIED", f"Blueprint 4 rejected: {res.failure_reasons}\nChecks: {res.checks}"
    assert set(res.verified_theorems) == {
        "ledger_spec_nonvacuous",
        "step_conserves_total_balance",
        "step_idempotent_on_seen_key",
        "trace_conserves_total_balance",
        "trace_preserves_nonneg_balances",
        "trace_seenKeys_monotone",
    }
    # Every axiom used must be inside the strict allowlist (for this ledger proof, even zero or propext only!)
    assert set(res.axioms_used).issubset({"propext", "Classical.choice", "Quot.sound"})
    assert "PASS" in res.checks["differential_conformance"]
    assert "1000/1000" in res.checks["differential_conformance"]
    assert att_path.exists()
    att = json.loads(att_path.read_text(encoding="utf-8"))
    assert att["verdict"] == "VERIFIED"
    assert len(att["attestation_sha256"]) == 64
