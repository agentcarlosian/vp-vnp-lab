"""End-to-end Palomar + multi-language differential conformance tests for Blueprints 06 (TS), 07 (Rust), and 08 (ZK/Replay)."""

from __future__ import annotations

import os
import pathlib
import shutil
import sys

import pytest

PKG_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from pcvh.config import load_spec_config
from pcvh.tcb.palomar_gate import run_palomar_gate
from tests._lean_env import detect_lean_bin

LOCAL_LEAN_BIN = detect_lean_bin(PKG_ROOT)


def _has_cargo() -> bool:
    if shutil.which("cargo"):
        return True
    cand = pathlib.Path.home() / ".cargo" / "bin" / ("cargo.exe" if os.name == "nt" else "cargo")
    return cand.exists()


def _has_node_or_tsx() -> bool:
    return bool(shutil.which("node") or shutil.which("tsx"))


@pytest.mark.skipif(LOCAL_LEAN_BIN is None or not _has_node_or_tsx(), reason="Lean 4.33.1 or Node.js missing")
def test_blueprint06_ai_agent_capability_guard_typescript_verified():
    bp = PKG_ROOT / "blueprints" / "06_agent_tool_guard"
    cfg = load_spec_config(bp)
    res = run_palomar_gate(
        cfg, trusted_local=True,
        lean_bin=LOCAL_LEAN_BIN,
        run_conformance=True,
        attestation_out=bp / "proof-attestation.json",
    )
    assert res.verdict == "VERIFIED", f"Blueprint 06 failed: {res.failure_reasons}"
    assert len(res.verified_theorems) == 7
    assert "1000/1000" in res.checks["differential_conformance"]


@pytest.mark.skipif(LOCAL_LEAN_BIN is None or not _has_cargo(), reason="Lean 4.33.1 or Rust Cargo missing")
def test_blueprint07_orderbook_and_margin_rust_verified():
    bp = PKG_ROOT / "blueprints" / "07_orderbook_matching"
    cfg = load_spec_config(bp)
    res = run_palomar_gate(
        cfg, trusted_local=True,
        lean_bin=LOCAL_LEAN_BIN,
        run_conformance=True,
        attestation_out=bp / "proof-attestation.json",
    )
    assert res.verdict == "VERIFIED", f"Blueprint 07 failed: {res.failure_reasons}"
    assert len(res.verified_theorems) == 6
    assert "1000/1000" in res.checks["differential_conformance"]


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4.33.1 toolchain missing")
def test_blueprint08_zk_gadgets_and_replay_window_verified():
    bp = PKG_ROOT / "blueprints" / "08_zk_and_replay_window"
    cfg = load_spec_config(bp)
    res = run_palomar_gate(
        cfg, trusted_local=True,
        lean_bin=LOCAL_LEAN_BIN,
        run_conformance=True,
        attestation_out=bp / "proof-attestation.json",
    )
    assert res.verdict == "VERIFIED", f"Blueprint 08 failed: {res.failure_reasons}"
    assert len(res.verified_theorems) == 8
    assert "1000/1000" in res.checks["differential_conformance"]
