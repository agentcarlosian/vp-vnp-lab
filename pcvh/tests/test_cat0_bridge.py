"""End-to-end test: CVXPY CAT(0) SOCP -> Lean 4 Proof Synthesis -> Zero-Trust Palomar Verification Gate."""

from __future__ import annotations

import math
import pathlib
import sys

import pytest

PKG_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from pcvh.cat0_bridge import synthesize_and_verify_cat0_blueprint
from tests._lean_env import detect_lean_bin

BLUEPRINT5_DIR = PKG_ROOT / "blueprints" / "05_cat0_certificate"
LOCAL_LEAN_BIN = detect_lean_bin(BLUEPRINT5_DIR)


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4.33.1 toolchain missing")
def test_cvxpy_cat0_socp_to_palomar_verified_lean4_proof():
    res = synthesize_and_verify_cat0_blueprint(BLUEPRINT5_DIR, lean_bin=LOCAL_LEAN_BIN)
    assert math.isclose(res.c4_rho_cat0, 1.0, rel_tol=1e-3)
    assert math.isclose(res.c4_compression_ratio, math.sqrt(2.0), rel_tol=1e-3)
    assert math.isclose(res.q3_rho_cat0, 1.0, rel_tol=2e-3)
    assert math.isclose(res.q3_compression_ratio, math.sqrt(3.0), rel_tol=2e-3)

    gate = res.gate_result
    assert gate.verdict == "VERIFIED", f"Blueprint 5 rejected: {gate.failure_reasons}\nChecks: {gate.checks}"
    assert set(gate.verified_theorems) == {
        "c4_crossing_cat0_bound",
        "cat0_spec_nonvacuous",
        "q3_cube_crossing_linear_bound",
        "q3_cube_enflo_squared_bound",
    }
    assert set(gate.axioms_used).issubset({"propext", "Classical.choice", "Quot.sound"})
    assert (BLUEPRINT5_DIR / "proof-attestation.json").exists()
