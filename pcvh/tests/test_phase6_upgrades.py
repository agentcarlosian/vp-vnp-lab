"""End-to-end tests for PCVH Phase 6 Upgrades:
  1. Multi-language adapters & `pcvh init` (live Rust cargo, live TypeScript Node.js, Solidity/Foundry)
  2. Real LLM provider wire protocols (Anthropic, OpenAI, Ollama), Best-First LSP Tree Search w/ backtracking,
     and `lean-orch` commit-gated multi-worker parallel lemma proving
  3. True Dual-Kernel (`lean4export` + `nanoda`) verification + Ed25519 DSSE cryptographic attestation signing
  4. Interactive `pcvh studio` local Web UI REST + Live Lean 4 LSP + Async Job API
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import pathlib
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple

import pytest

PKG_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from pcvh.adapters.scaffolder import scaffold_project
from pcvh.agents.llm_providers import (
    AnthropicLLMBackend,
    OllamaLLMBackend,
    OpenAILLMBackend,
    create_llm_backend,
    describe_available_providers,
)
from pcvh.agents.orchestrator import compute_commit_gated_workers, run_autonomous_prove_pipeline
from pcvh.agents.planner import build_proof_plan
from pcvh.agents.prover import ProofPromptContext
from pcvh.agents.retriever import PremiseIndex
from pcvh.agents.tree_search import BestFirstProofSearch, TreeSearchConfig
from pcvh.config import load_spec_config
from pcvh.studio.server import create_studio_server
from pcvh.tcb.crypto import (
    generate_ed25519_keypair,
    sign_attestation_file,
    verify_attestation_file,
    verify_attestation_signature,
)
from pcvh.tcb.dual_kernel import run_dual_kernel_verification
from pcvh.tcb.manifest import pin_tcb_manifest
from pcvh.tcb.palomar_gate import _run_with_transient_oom_retry, run_palomar_gate
from tests._lean_env import LAKE_EXE_NAME, detect_lean_bin

LOCAL_LEAN_BIN = detect_lean_bin(PKG_ROOT)


# ==============================================================================
# 1. Multi-Language Production Adapters & `pcvh init`
# ==============================================================================

@pytest.mark.skipif(LOCAL_LEAN_BIN is None or shutil.which("cargo") is None, reason="Lean 4 or Rust cargo missing")
def test_phase6_rust_adapter_init_prove_and_cargo_conformance_e2e(tmp_path: pathlib.Path):
    """Scaffold Rust project -> autonomously prove all 5 Lean theorems -> verify live `cargo test` + 500 Rust traces."""
    dest = tmp_path / "rust_ratelimit"
    scaf = scaffold_project(dest, language="rust", template="ratelimit", auto_pin=True)
    assert scaf.pinned and (dest / "Cargo.toml").exists() and (dest / "src" / "lib.rs").exists()

    cfg = load_spec_config(dest)
    assert cfg.target_language == "rust"

    res = run_autonomous_prove_pipeline(cfg, lean_bin=LOCAL_LEAN_BIN, parallel_workers=2)
    assert res.status == "VERIFIED", f"Rust adapter pipeline failed: {res.to_dict()}"
    assert res.gate_result is not None and res.gate_result.verdict == "VERIFIED"
    assert len(res.gate_result.verified_theorems) == 5
    assert "500/500 Rust cargo differential traces matched bit-for-bit" in res.gate_result.checks["differential_conformance"]


@pytest.mark.skipif(LOCAL_LEAN_BIN is None or shutil.which("node") is None, reason="Lean 4 or Node.js missing")
def test_phase6_typescript_adapter_init_prove_and_node_conformance_e2e(tmp_path: pathlib.Path):
    """Scaffold TypeScript project -> autonomously prove all 4 Lean theorems -> verify live Node.js TS 500 traces."""
    dest = tmp_path / "ts_ledger"
    scaf = scaffold_project(dest, language="typescript", template="ledger", auto_pin=True)
    assert scaf.pinned and (dest / "package.json").exists() and (dest / "src" / "target.ts").exists()

    cfg = load_spec_config(dest)
    assert cfg.target_language == "typescript"

    res = run_autonomous_prove_pipeline(cfg, lean_bin=LOCAL_LEAN_BIN, parallel_workers=2)
    assert res.status == "VERIFIED", f"TypeScript adapter pipeline failed: {res.to_dict()}"
    assert res.gate_result is not None and res.gate_result.verdict == "VERIFIED"
    assert len(res.gate_result.verified_theorems) == 4
    assert "500/500 TypeScript Node.js differential traces matched bit-for-bit" in res.gate_result.checks["differential_conformance"]


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4 toolchain missing")
def test_phase6_solidity_foundry_adapter_init_prove_and_conformance_e2e(tmp_path: pathlib.Path):
    """Scaffold Solidity/Foundry project (`foundry.toml`, `Target.sol`, `Conformance.t.sol`) -> prove & Palomar-verify."""
    dest = tmp_path / "sol_ratelimit"
    scaf = scaffold_project(dest, language="solidity", template="ratelimit", auto_pin=True)
    assert scaf.pinned
    assert (dest / "foundry.toml").exists()
    assert (dest / "src" / "Target.sol").exists()
    assert (dest / "test" / "Conformance.t.sol").exists()

    cfg = load_spec_config(dest)
    assert cfg.target_language == "solidity"
    res = run_autonomous_prove_pipeline(cfg, lean_bin=LOCAL_LEAN_BIN, parallel_workers=2)
    assert res.status == "VERIFIED", f"Solidity adapter pipeline failed: {res.to_dict()}"
    assert res.gate_result is not None and res.gate_result.verdict == "VERIFIED"
    assert "500/500 Solidity uint256 model differential traces matched bit-for-bit" in res.gate_result.checks["differential_conformance"]


# ==============================================================================
# 2. Multi-Provider LLM Wire Protocols, Best-First LSP Tree Search & Parallel Waves
# ==============================================================================

def test_phase6_llm_providers_wire_protocols_anthropic_openai_ollama():
    """Verify real HTTP wire protocols, auth headers, response parsing, and cost accounting for all 3 LLM providers."""
    captured: List[Tuple[str, Dict[str, str], Dict[str, Any]]] = []

    class _MockLLMHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            hdrs = {k.lower(): v for k, v in self.headers.items()}
            captured.append((self.path, hdrs, body))

            is_step = "JSON array" in str(body)
            reply_text = '["unfold f", "omega"]' if is_step else "```lean4\nomega\n```"

            if self.path == "/v1/messages":
                assert hdrs.get("x-api-key") == "mock-anthropic-token"
                assert hdrs.get("anthropic-version") == "2023-06-01"
                resp = {
                    "content": [{"type": "text", "text": reply_text}],
                    "usage": {"input_tokens": 1000, "output_tokens": 200},
                }
            elif self.path == "/v1/chat/completions":
                assert hdrs.get("authorization") == "Bearer mock-openai-token"
                resp = {
                    "choices": [{"message": {"content": reply_text}}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
                }
            elif self.path == "/api/chat":
                assert body.get("stream") is False
                resp = {"message": {"role": "assistant", "content": reply_text}}
            else:
                self.send_response(404)
                self.end_headers()
                return

            raw = json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockLLMHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        ctx = ProofPromptContext(
            theorem_name="demo",
            theorem_signature="theorem demo (n : Nat) : n + 0 = n",
            module_header="import Specs.Statement",
            round_idx=1,
            live_lsp_goals=["n : Nat\n⊢ n + 0 = n"],
            retrieved_premises_text="(none)",
        )

        # Anthropic Messages API
        ant = AnthropicLLMBackend(api_key="mock-anthropic-token", base_url=f"http://127.0.0.1:{port}/v1/messages")
        proof, cost = ant.propose_tactic_proof(ctx)
        assert proof == "omega" and cost > 0
        steps, scost = ant.propose_tactic_steps(ctx.theorem_signature, [], ctx.live_lsp_goals, "", k=3)
        assert steps == ["unfold f", "omega"] and scost > 0

        # OpenAI Chat Completions API
        oai = OpenAILLMBackend(api_key="mock-openai-token", base_url=f"http://127.0.0.1:{port}/v1/chat/completions")
        proof2, cost2 = oai.propose_tactic_proof(ctx)
        assert proof2 == "omega" and cost2 > 0
        steps2, _ = oai.propose_tactic_steps(ctx.theorem_signature, [], ctx.live_lsp_goals, "", k=3)
        assert steps2 == ["unfold f", "omega"]

        # Local Ollama REST API ($0.00 cost)
        oll = OllamaLLMBackend(model="qwen2.5-coder:14b", base_url=f"http://127.0.0.1:{port}")
        proof3, cost3 = oll.propose_tactic_proof(ctx)
        assert proof3 == "omega" and cost3 == 0.0
        steps3, scost3 = oll.propose_tactic_steps(ctx.theorem_signature, [], ctx.live_lsp_goals, "", k=3)
        assert steps3 == ["unfold f", "omega"] and scost3 == 0.0

        assert create_llm_backend("none") is None
        assert isinstance(create_llm_backend("ollama", base_url=f"http://127.0.0.1:{port}"), OllamaLLMBackend)
        assert len(describe_available_providers()) == 3
        assert len(captured) == 6
    finally:
        srv.shutdown()
        srv.server_close()


class _BacktrackingTreePolicy:
    """Proposes a deliberately invalid first step (forcing LSP backtracking!) before valid multi-step proof."""

    def propose_tactic_steps(self, sig, prefix, goals, premises, k=4):
        if not prefix:
            return ["exact nonexistent_dead_end_lemma", "simp only [clampMax]"], 0.005
        return ["split", "omega"], 0.005


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4 toolchain missing")
def test_phase6_best_first_lsp_tree_search_with_backtracking(tmp_path: pathlib.Path):
    """Exercise live Lean 4 LSP `didChange` best-first proof-tree search with genuine error backtracking."""
    proj = tmp_path / "tree_search_demo"
    (proj / "Specs").mkdir(parents=True)
    (proj / "lean-toolchain").write_text("leanprover/lean4:v4.33.1\n", encoding="utf-8")
    (proj / "lakefile.toml").write_text(
        'name = "tree_demo"\ndefaultTargets = ["Specs.Challenge", "Solution"]\n\n'
        '[[lean_lib]]\nname = "Specs"\n\n[[lean_lib]]\nname = "Solution"\n',
        encoding="utf-8",
    )
    (proj / "pcvh.toml").write_text(
        '[spec]\nname = "tree-demo"\nlean_toolchain = "leanprover/lean4:v4.33.1"\n'
        'statement = "Specs/Statement.lean"\nchallenge = "Specs/Challenge.lean"\n'
        'challenge_module = "Specs.Challenge"\nsolution_module = "Solution"\n'
        'require_nonvacuity_witness = false\n',
        encoding="utf-8",
    )
    (proj / "Specs" / "Statement.lean").write_text(
        "namespace Clamp\n"
        "def clampMax (x cap : Nat) : Nat := if x ≤ cap then x else cap\n"
        "end Clamp\n",
        encoding="utf-8",
    )
    (proj / "Specs" / "Challenge.lean").write_text(
        "import Specs.Statement\n"
        "namespace Challenge\n"
        "open Clamp\n"
        "theorem clamp_le_cap (x cap : Nat) : clampMax x cap ≤ cap := by sorry\n"
        "end Challenge\n",
        encoding="utf-8",
    )

    cfg = load_spec_config(proj)
    pin_tcb_manifest(cfg, save_snapshot=True)
    env = dict(os.environ, PATH=str(LOCAL_LEAN_BIN) + os.pathsep + os.environ.get("PATH", ""))
    _run_with_transient_oom_retry([str(LOCAL_LEAN_BIN / LAKE_EXE_NAME), "build", "Specs.Statement"], cwd=proj, env=env)

    plan = build_proof_plan(cfg)
    task = plan.tasks[0]
    searcher = BestFirstProofSearch(
        cfg,
        plan,
        PremiseIndex(),
        lean_bin=LOCAL_LEAN_BIN,
        llm_backend=_BacktrackingTreePolicy(),
        search_config=TreeSearchConfig(max_expansions=16, max_depth=4, max_seconds=30.0),
    )
    ts_res = searcher.search(task, [], [], proj / task.rel_file_path)
    assert ts_res.proved, f"Best-first tree search failed: {ts_res.last_errors}"
    assert ts_res.backtracks >= 1, "Expected at least one backtrack from the dead-end branch!"
    assert ts_res.nodes_expanded >= 2
    assert len(ts_res.tactic_steps) >= 2


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4 toolchain missing")
def test_phase6_commit_gated_parallel_wave_proving(tmp_path: pathlib.Path):
    """Verify `lean-orch` commit-gated multi-worker topological wave execution proves multi-wave DAGs."""
    allowed, commit_gb = compute_commit_gated_workers(2)
    assert allowed >= 1
    if sys.platform == "win32":
        assert commit_gb >= 0.0

    dest = tmp_path / "parallel_waves"
    scaffold_project(dest, language="python", template="ratelimit", auto_pin=True)
    cfg = load_spec_config(dest)
    res = run_autonomous_prove_pipeline(cfg, lean_bin=LOCAL_LEAN_BIN, parallel_workers=2)
    assert res.status == "VERIFIED", f"Parallel wave pipeline failed: {res.to_dict()}"
    assert res.waves_executed >= 2  # refill/tryConsume wave + downstream postTokens/step wave!
    assert len(res.proof_results) == 5


# ==============================================================================
# 3. Cryptographic Ed25519 DSSE Signing & Independent Dual-Kernel Runner
# ==============================================================================

@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4 toolchain missing")
def test_phase6_ed25519_dsse_signing_verification_and_tamper_rejection(tmp_path: pathlib.Path):
    """Sign a real Palomar gate attestation with Ed25519 DSSEv1, verify it, and confirm 3 tamper attacks fail."""
    dest = tmp_path / "signed_proj"
    scaffold_project(dest, language="python", template="ledger", auto_pin=True)
    cfg = load_spec_config(dest)
    prove_res = run_autonomous_prove_pipeline(cfg, lean_bin=LOCAL_LEAN_BIN)
    assert prove_res.status == "VERIFIED"

    kp = generate_ed25519_keypair(tmp_path / "keys")
    kp_wrong = generate_ed25519_keypair(tmp_path / "wrong_keys")
    att_fp = dest / "proof-attestation.json"

    gate = run_palomar_gate(
        cfg, trusted_local=True,
        lean_bin=LOCAL_LEAN_BIN,
        run_conformance=False,
        sign_key_path=kp.private_key_path,
        attestation_out=att_fp,
    )
    assert gate.verdict == "VERIFIED"
    assert gate.signature_envelope is not None

    # 1. Valid Ed25519 DSSE signature verifies cleanly
    v_ok = verify_attestation_file(att_fp, kp.public_key_path)
    assert v_ok.ok and v_ok.algorithm == "Ed25519-DSSEv1" and v_ok.key_id == kp.key_id

    # 2. Wrong public key MUST fail
    v_wrong_key = verify_attestation_file(att_fp, kp_wrong.public_key_path)
    assert not v_wrong_key.ok

    # 3. Tampering with `verified_theorems` MUST fail (SHA-256 + DSSE payload mismatch)
    tampered = json.loads(att_fp.read_text(encoding="utf-8"))
    tampered["verified_theorems"].append("forged_theorem_claim")
    v_tamper_1 = verify_attestation_signature(tampered, kp.public_key_pem)
    assert not v_tamper_1.ok

    # 4. Recomputing `attestation_sha256` after tampering `verdict` STILL fails DSSE signature check!
    tampered2 = json.loads(att_fp.read_text(encoding="utf-8"))
    tampered2["verdict"] = "TAMPERED"
    v_tamper_2 = verify_attestation_signature(tampered2, kp.public_key_pem)
    assert not v_tamper_2.ok

    # 5. Standalone `sign_attestation_file` re-signs cleanly
    re_signed = sign_attestation_file(att_fp, kp.private_key_path)
    assert verify_attestation_signature(re_signed, kp.public_key_pem).ok


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4 toolchain missing")
def test_phase6_dual_kernel_runner_strict_enforcement_and_export_replay(tmp_path: pathlib.Path, monkeypatch):
    """Verify `--require-dual-kernel` fails closed when tools are absent, and replays export->nanoda when present."""
    dest = tmp_path / "dk_proj"
    scaffold_project(dest, language="python", template="ledger", auto_pin=True)
    cfg = load_spec_config(dest)
    assert run_autonomous_prove_pipeline(cfg, lean_bin=LOCAL_LEAN_BIN).status == "VERIFIED"

    # 1. Strict mode fails closed when lean4export/nanoda are absent
    monkeypatch.delenv("COMPARATOR_LEAN4EXPORT", raising=False)
    monkeypatch.delenv("COMPARATOR_NANODA", raising=False)
    monkeypatch.delenv("COMPARATOR_BIN", raising=False)
    if not (shutil.which("lean4export") and (shutil.which("nanoda_bin") or shutil.which("nanoda"))):
        strict_gate = run_palomar_gate(cfg, trusted_local=True, lean_bin=LOCAL_LEAN_BIN, run_conformance=False, require_dual_kernel=True)
        assert strict_gate.verdict == "REJECTED"
        assert "FAIL" in strict_gate.checks["external_second_kernel"]

    # 2. Direct `lean4export` -> `nanoda` runner path (test both ACCEPT and REJECT kernel verdicts)
    bin_dir = tmp_path / "fake_dk_bins"
    bin_dir.mkdir()
    if os.name == "nt":
        exp_shim = bin_dir / "lean4export.cmd"
        nan_ok = bin_dir / "nanoda_ok.cmd"
        nan_bad = bin_dir / "nanoda_bad.cmd"
        exp_shim.write_text("@echo off\necho #NS 1 Solution\necho #DEF 1 0\n", encoding="utf-8")
        nan_ok.write_text("@echo off\nif not exist \"%~1\" exit /b 2\necho nanoda replay OK\nexit /b 0\n", encoding="utf-8")
        nan_bad.write_text("@echo off\necho nanoda kernel type error >&2\nexit /b 1\n", encoding="utf-8")
    else:
        exp_shim = bin_dir / "lean4export"
        nan_ok = bin_dir / "nanoda_ok"
        nan_bad = bin_dir / "nanoda_bad"
        exp_shim.write_text("#!/bin/sh\necho '#NS 1 Solution'\necho '#DEF 1 0'\n", encoding="utf-8")
        nan_ok.write_text("#!/bin/sh\ntest -s \"$1\" && echo 'nanoda replay OK'\n", encoding="utf-8")
        nan_bad.write_text("#!/bin/sh\necho 'nanoda kernel type error' >&2\nexit 1\n", encoding="utf-8")
        for p in (exp_shim, nan_ok, nan_bad):
            p.chmod(0o755)

    ws = tmp_path / "dk_ws"
    ws.mkdir()
    env = dict(os.environ, PATH=str(LOCAL_LEAN_BIN) + os.pathsep + os.environ.get("PATH", ""))

    monkeypatch.setenv("COMPARATOR_LEAN4EXPORT", str(exp_shim))
    monkeypatch.setenv("COMPARATOR_NANODA", str(nan_ok))
    dk_pass = run_dual_kernel_verification(
        ws,
        cfg,
        lake_exe=LOCAL_LEAN_BIN / LAKE_EXE_NAME,
        env=env,
        require_dual_kernel=True,
    )
    assert dk_pass.ok and dk_pass.status == "PASS" and dk_pass.backend == "lean4export+nanoda"
    assert dk_pass.exported_lines >= 2
    assert (ws / "comparator.json").exists()

    monkeypatch.setenv("COMPARATOR_NANODA", str(nan_bad))
    dk_fail = run_dual_kernel_verification(
        ws,
        cfg,
        lake_exe=LOCAL_LEAN_BIN / LAKE_EXE_NAME,
        env=env,
        require_dual_kernel=True,
    )
    assert not dk_fail.ok and dk_fail.status == "FAIL"


# ==============================================================================
# 4. Interactive `pcvh studio` Local Web UI Server (REST + Live Lean 4 LSP + Jobs)
# ==============================================================================

_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http_json(
    url: str,
    payload: Dict[str, Any] | None = None,
    *,
    headers: Dict[str, str] | None = None,
) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req_headers = {"Content-Type": "application/json"} if payload is not None else {}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST" if payload is not None else "GET")
    try:
        with _NO_PROXY_OPENER.open(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4 toolchain missing")
def test_phase6_studio_web_ui_rest_lsp_and_action_jobs(tmp_path: pathlib.Path, monkeypatch):
    """Spin up live `pcvh studio` server and verify UI HTML, overview, project view, live Lean LSP, async verify job, signing & security."""
    monkeypatch.setenv("PCVH_STUDIO_KEY_DIR", str(tmp_path / "studio-keys"))
    ws_root = tmp_path / "studio_ws"
    ws_root.mkdir()

    # Start Studio HTTP server on ephemeral port 0
    srv = create_studio_server(ws_root, host="127.0.0.1", port=0, lean_bin=LOCAL_LEAN_BIN)
    port = srv.server_address[1]
    base = f"http://127.0.0.1:{port}"
    auth_hdr = {"X-PCVH-Token": srv.studio_state.csrf_token}
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()

    try:
        # 1. GET / serves standalone Studio Web UI HTML, plus /showcase and /eval routes
        with _NO_PROXY_OPENER.open(f"{base}/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "PCVH Studio" in html and "$/lean/plainGoal" in html
            assert srv.studio_state.csrf_token not in html
        with _NO_PROXY_OPENER.open(f"{base}/showcase", timeout=10) as resp:
            assert resp.status == 200 and b"Eight Machine-Checked Engineering Specifications" in resp.read()
        with _NO_PROXY_OPENER.open(f"{base}/eval", timeout=10) as resp:
            assert resp.status == 200 and b"40-Invariant" in resp.read()

        # 2. POST /api/init scaffolds a new project inside workspace root
        code, init_res = _http_json(
            f"{base}/api/init",
            {"dir": "demo_ledger", "language": "python", "template": "ledger"},
            headers=auth_hdr,
        )
        assert code == 201 and init_res["pinned"] is True

        # 3. GET /api/overview discovers the scaffolded project & reports Lean + memory + LLM providers
        code, ov = _http_json(f"{base}/api/overview", headers=auth_hdr)
        assert code == 200
        assert ov["lean_bin"] is not None
        assert any(p["id"] == "demo_ledger" for p in ov["projects"])

        # 4. GET /api/project returns spec files & TCB status
        code, det = _http_json(f"{base}/api/project?id=demo_ledger", headers=auth_hdr)
        assert code == 200 and det["tcb_ok"] is True
        assert "Specs/LedgerCore/Challenge.lean" in det["files"]

        # 5. Path-traversal attack is rejected with 400
        code_bad, _ = _http_json(f"{base}/api/project?id=../../outside", headers=auth_hdr)
        assert code_bad == 400

        # 6. POST /api/lsp/goals queries live Lean 4.33.1 LSP at the `sorry` line in Challenge.lean!
        chall_lines = det["files"]["Specs/LedgerCore/Challenge.lean"].splitlines()
        sorry_line = next(i + 1 for i, ln in enumerate(chall_lines) if ln.strip() == "sorry")
        code, lsp_res = _http_json(
            f"{base}/api/lsp/goals",
            {
                "project_id": "demo_ledger",
                "rel_file": "Specs/LedgerCore/Challenge.lean",
                "line": sorry_line,
                "col": 2,
            },
            headers=auth_hdr,
        )
        assert code == 200
        assert any("⊢" in g for g in lsp_res["goals"]), f"Expected live Lean goal, got: {lsp_res}"

        # 7. POST /api/action (`prove`) runs asynchronously and produces a VERIFIED attestation!
        code, job = _http_json(f"{base}/api/action", {"project_id": "demo_ledger", "action": "prove"}, headers=auth_hdr)
        assert code == 202 and job["job_id"]
        deadline = time.time() + 120.0
        final_job = job
        while time.time() < deadline:
            _, final_job = _http_json(f"{base}/api/job?id={job['job_id']}", headers=auth_hdr)
            if final_job["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.5)
        assert final_job["status"] == "succeeded", f"Studio async prove job failed: {final_job}"
        assert final_job["result"]["status"] == "VERIFIED"

        # 8. One-click Studio signing (`POST /api/sign`) + verification (`POST /api/verify-sig`) + sub-lemma tabs!
        code, sign_res = _http_json(f"{base}/api/sign", {"project_id": "demo_ledger"}, headers=auth_hdr)
        assert code == 200 and sign_res["ok"] is True and sign_res["public_key_pem"]

        code, sig_res = _http_json(
            f"{base}/api/verify-sig",
            {"project_id": "demo_ledger", "public_key_pem": sign_res["public_key_pem"]},
            headers=auth_hdr,
        )
        assert code == 200 and sig_res["ok"] is True

        # Verify synthesized `Solution/Lem_*.lean` and `target.py` are exposed in Studio tabs
        _, det_after = _http_json(f"{base}/api/project?id=demo_ledger", headers=auth_hdr)
        assert "target.py" in det_after["files"]
        assert any(k.startswith("Solution/Lem_") for k in det_after["files"])

        # 9. Verify TCB file-save protection (`POST /api/file`) + live unsaved buffer LSP check
        code_tcb_blocked, _ = _http_json(
            f"{base}/api/file",
            {"project_id": "demo_ledger", "path": "Specs/LedgerCore/Challenge.lean", "content": "-- blocked"},
            headers=auth_hdr,
        )
        assert code_tcb_blocked == 400

        unsaved_lean = det_after["files"]["Specs/LedgerCore/Challenge.lean"].replace("by sorry", "by\n  sorry", 1)
        code_buf, buf_lsp = _http_json(
            f"{base}/api/lsp/goals",
            {
                "project_id": "demo_ledger",
                "rel_file": "Specs/LedgerCore/Challenge.lean",
                "line": sorry_line + 1,
                "col": 2,
                "content": unsaved_lean,
            },
            headers=auth_hdr,
        )
        assert code_buf == 200 and "goals" in buf_lsp

        code_save_ok, save_res = _http_json(
            f"{base}/api/file",
            {"project_id": "demo_ledger", "path": "target.py", "content": det_after["files"]["target.py"]},
            headers=auth_hdr,
        )
        assert code_save_ok == 200 and save_res["ok"] is True
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4 toolchain missing")
def test_phase6_vault_template_autonomous_division_prover(tmp_path: pathlib.Path):
    """Verify nonlinear ERC-4626 + AMM `vault` template proves all 5 theorems autonomously and passes Palomar Gate."""
    dest = tmp_path / "py_vault"
    scaffold_project(dest, language="python", template="vault", auto_pin=True)
    cfg = load_spec_config(dest)
    res = run_autonomous_prove_pipeline(cfg, lean_bin=LOCAL_LEAN_BIN, parallel_workers=2)
    assert res.status == "VERIFIED", f"Vault template autonomous prove failed: {res.to_dict()}"
    assert res.gate_result is not None and len(res.gate_result.verified_theorems) == 5


def test_phase6_static_audit_blocks_guillemets_csimp_and_compile_time_eval(tmp_path: pathlib.Path):
    """Verify hardened static anti-cheat scanner catches escaped `«sorry»`, `@[csimp]`, `#eval`, and `run_cmd`."""
    from pcvh.tcb.static_audit import scan_untrusted_lean_files

    proj = tmp_path / "audit_hardening"
    scaffold_project(proj, language="python", template="ledger", auto_pin=True)
    cfg = load_spec_config(proj)

    (proj / "Solution.lean").write_text(
        "import Specs.LedgerCore.Statement\n"
        "#eval IO.println \"sneaky compile-time IO\"\n"
        "run_cmd pure ()\n"
        "@[csimp] theorem bad_swap : id = id := «sorry»\n",
        encoding="utf-8",
    )
    audit = scan_untrusted_lean_files(proj, cfg)
    assert not audit.ok
    rules = {v.rule for v in audit.violations}
    assert "banned_sorry" in rules
    assert "banned_extern" in rules
    assert "banned_compile_time_exec" in rules


def test_phase6_static_audit_blocks_char_literal_raw_string_and_metaprogramming(tmp_path: pathlib.Path):
    """Ensure char literals (`'\"'`), raw strings, and metaprogramming hooks cannot blind the static audit."""
    from pcvh.tcb.static_audit import scan_untrusted_lean_files

    proj = tmp_path / "audit_char_bypass"
    scaffold_project(proj, language="python", template="ledger", auto_pin=True)
    cfg = load_spec_config(proj)

    (proj / "Solution.lean").write_text(
        "import Specs.LedgerCore.Statement\n"
        "def q : Char := '\"'\n"
        "def r : String := r#\"benign \" sorry\"#\n"
        "def x' : Nat := 1\n"
        "def y' : Nat := x' + 1\n"
        "initialize pure ()\n"
        "macro \"sneak\" : term => `(sorry)\n"
        "#eval IO.println \"pwned\"\n"
        "unsafe def bad := sorry\n",
        encoding="utf-8",
    )
    audit = scan_untrusted_lean_files(proj, cfg)
    assert not audit.ok
    rules = {v.rule for v in audit.violations}
    assert "banned_sorry" in rules
    assert "banned_unsafe" in rules
    assert "banned_compile_time_exec" in rules


def test_phase6_studio_csrf_origin_host_and_tcb_protection(tmp_path: pathlib.Path):
    """Verify Studio rejects cross-origin/CSRF POSTs, DNS-rebinding Host headers, and unprotected pcvh.toml writes."""
    ws_root = tmp_path / "studio_sec"
    ws_root.mkdir()
    scaffold_project(ws_root / "demo", language="python", template="ledger", auto_pin=True)

    srv = create_studio_server(ws_root, host="127.0.0.1", port=0)
    port = srv.server_address[1]
    base = f"http://127.0.0.1:{port}"
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        assert _http_json(f"{base}/api/overview")[0] == 403
        # Missing CSRF token -> 403
        code, _ = _http_json(f"{base}/api/action", {"project_id": "demo", "action": "pin"})
        assert code == 403

        # Wrong Content-Type (simple CORS text/plain) -> 415
        code, _ = _http_json(
            f"{base}/api/action",
            {"project_id": "demo", "action": "pin"},
            headers={"Content-Type": "text/plain", "X-PCVH-Token": srv.studio_state.csrf_token},
        )
        assert code == 415

        # Cross-origin Origin header -> 403
        code, _ = _http_json(
            f"{base}/api/action",
            {"project_id": "demo", "action": "pin"},
            headers={"Origin": "https://evil.example", "X-PCVH-Token": srv.studio_state.csrf_token},
        )
        assert code == 403

        # DNS-rebinding Host header -> 403
        code, _ = _http_json(
            f"{base}/api/overview",
            headers={"Host": "rebind.evil.example"},
        )
        assert code == 403

        # Valid token still blocks overwriting pcvh.toml without allow_tcb=True
        code, _ = _http_json(
            f"{base}/api/file",
            {"project_id": "demo", "path": "pcvh.toml", "content": "# tampered"},
            headers={"X-PCVH-Token": srv.studio_state.csrf_token},
        )
        assert code == 400
    finally:
        srv.shutdown()
        srv.server_close()
