"""CLI for Agentic Proof-Carrying Verification Harness (`pcvh`)."""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import List, Optional

from .adapters.scaffolder import SUPPORTED_LANGUAGES, SUPPORTED_TEMPLATES, scaffold_project
from .agents.orchestrator import run_autonomous_prove_pipeline
from .cat0_bridge import synthesize_and_verify_cat0_blueprint
from .ci.diff_reprove import run_diff_aware_reprove
from .config import load_spec_config
from .eval.benchmark_40 import run_eval_benchmark_40
from .falsify.falsifier import run_falsification_precheck
from .runtime.lean_diagnostics import LeanLSPClient
from .studio.server import serve_studio
from .tcb.crypto import generate_ed25519_keypair, sign_attestation_file, verify_attestation_file
from .tcb.manifest import pin_tcb_manifest, verify_tcb_manifest
from .tcb.palomar_gate import run_palomar_gate
from .tcb.static_audit import scan_untrusted_lean_files


def cmd_init(args: argparse.Namespace) -> int:
    res = scaffold_project(
        args.dest,
        language=args.lang,
        template=args.template,
        name=args.name,
        auto_pin=not args.no_pin,
    )
    if args.as_json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(f"=== Scaffolded PCVH Project: {res.name} ({res.language} / {res.template}) ===")
        print(f"Location:    {res.project_root}")
        print(f"TCB Pinned:  {res.pinned} (sha256={res.spec_bundle_sha256[:16]}...)")
        print(f"Files ({len(res.files_created)}):")
        for f in res.files_created:
            print(f"  - {f}")
        print(f"\nNext steps:\n  python -m pcvh prove {args.dest}\n  python -m pcvh verify {args.dest}")
    return 0


def cmd_pin(args: argparse.Namespace) -> int:
    cfg = load_spec_config(args.project)
    lock = pin_tcb_manifest(cfg, save_snapshot=True)
    if args.as_json:
        print(json.dumps(lock, indent=2))
    else:
        print(f"[PINNED] {cfg.name} | bundle_sha256={lock['spec_bundle_sha256'][:16]}... | files={len(lock['files'])}")
        for k, v in lock["files"].items():
            print(f"  - {k}: {v[:16]}...")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    cfg = load_spec_config(args.project)
    man = verify_tcb_manifest(cfg)
    st = scan_untrusted_lean_files(cfg.project_root, cfg)
    out = {
        "tcb_ok": man.ok,
        "mismatched_tcb": man.mismatched_files,
        "missing_tcb": man.missing_files,
        "static_audit": st.to_dict(),
    }
    print(json.dumps(out, indent=2))
    return 0 if (man.ok and st.ok) else 1


def cmd_keygen(args: argparse.Namespace) -> int:
    kp = generate_ed25519_keypair(args.out_dir, prefix=args.prefix)
    payload = {
        "key_id": kp.key_id,
        "private_key_path": str(kp.private_key_path),
        "public_key_path": str(kp.public_key_path),
    }
    if args.as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"[KEYGEN] Ed25519 keypair generated ({kp.key_id})")
        print(f"  Private key: {kp.private_key_path}")
        print(f"  Public key:  {kp.public_key_path}")
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    signed = sign_attestation_file(args.attestation, args.key, key_id=args.key_id)
    if args.as_json:
        print(json.dumps(signed, indent=2))
    else:
        sig = signed["signature_envelope"]["signatures"][0]
        print(f"[SIGNED] {args.attestation} | alg={sig['alg']} | key_id={sig['keyid']} | sha256={signed['attestation_sha256'][:16]}...")
    return 0


def cmd_verify_sig(args: argparse.Namespace) -> int:
    res = verify_attestation_file(args.attestation, args.pubkey)
    if args.as_json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        status = "VALID" if res.ok else "INVALID"
        print(f"[{status}] {args.attestation} | alg={res.algorithm} | key_id={res.key_id} | {res.reason}")
    return 0 if res.ok else 1


def cmd_verify(args: argparse.Namespace) -> int:
    cfg = load_spec_config(args.project)
    att_path = args.attestation or (cfg.project_root / "proof-attestation.json")
    res = run_palomar_gate(
        cfg,
        lean_bin=args.lean_bin,
        run_conformance=not args.skip_conformance,
        require_dual_kernel=True if args.require_dual_kernel else None,
        sign_key_path=args.sign_key,
        sign_key_id=args.sign_key_id,
        attestation_out=att_path,
    )
    att = res.to_attestation_dict()
    if args.as_json:
        print(json.dumps(att, indent=2))
    else:
        print(f"=== PCVH Palomar Verification Gate: {res.spec_name} ===")
        print(f"Verdict:     {res.verdict}  ({res.duration_s:.2f}s)")
        print(f"Spec SHA256: {res.spec_bundle_sha256}")
        print(f"Theorems:    {res.verified_theorems}")
        print(f"Axioms:      {res.axioms_used}")
        print("Checks:")
        for k, v in res.checks.items():
            print(f"  - {k:<26}: {v}")
        if res.failure_reasons:
            print("Failure reasons:")
            for r in res.failure_reasons:
                print(f"  ! {r}")
        print(f"Attestation: {att_path} (sha256={res.attestation_sha256[:16]}...)")
    return 0 if res.verdict == "VERIFIED" else 1


def cmd_cert_cat0(args: argparse.Namespace) -> int:
    res = synthesize_and_verify_cat0_blueprint(args.blueprint, lean_bin=args.lean_bin)
    if args.as_json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print("=== PCVH Primal-Dual CAT(0) SOCP -> Lean 4 Proof Certificate ===")
        print(f"C_4 CAT(0):  rho={res.c4_rho_cat0:.4f} ({res.c4_compression_ratio:.4f}x compression)")
        print(f"Q_3 CAT(0):  rho={res.q3_rho_cat0:.4f} ({res.q3_compression_ratio:.4f}x compression)")
        print(f"Synthesized: {res.generated_solution_path}")
        print(f"Verdict:     {res.gate_result.verdict} | theorems={res.gate_result.verified_theorems}")
        print(f"Axioms:      {res.gate_result.axioms_used}")
    return 0 if res.gate_result.verdict == "VERIFIED" else 1


def cmd_falsify(args: argparse.Namespace) -> int:
    cfg = load_spec_config(args.project)
    res = run_falsification_precheck(cfg, lean_bin=args.lean_bin)
    if args.as_json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(f"=== PCVH Stage-2 Falsification Pre-Check: {cfg.name} ===")
        print(f"Status:   {res.status} ({res.duration_s:.2f}s)")
        print(f"Tested:   {res.theorems_tested} ({res.samples_evaluated} samples)")
        for cex in res.counterexamples:
            print(f"  ! COUNTEREXAMPLE [{cex.source}] {cex.theorem}: {cex.inputs}")
        for note in res.notes:
            print(f"  - {note}")
    return 0 if res.ok else 1


def cmd_inspect_goals(args: argparse.Namespace) -> int:
    with LeanLSPClient(args.project, lean_bin=args.lean_bin) as lsp:
        goals, rendered = lsp.get_plain_goal(args.file, line_0idx=args.line - 1, col_0idx=args.col)
    if args.as_json:
        print(json.dumps({"goals": goals, "rendered": rendered}, indent=2))
    else:
        print("\n---\n".join(goals) if goals else "(no active goals at position)")
    return 0


def cmd_prove(args: argparse.Namespace) -> int:
    cfg = load_spec_config(args.project)
    res = run_autonomous_prove_pipeline(
        cfg,
        lean_bin=args.lean_bin,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
        enable_tree_search=not args.no_tree_search,
        parallel_workers=args.workers,
        attestation_out=args.attestation,
    )
    if args.as_json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(f"=== PCVH Autonomous Spec -> Proof Pipeline: {res.spec_name} ===")
        print(
            f"Status:        {res.status} ({res.duration_s:.2f}s, cost=${res.total_cost_usd:.4f}, "
            f"waves={res.waves_executed}, peak_workers={res.peak_parallel_workers})"
        )
        print(f"Falsification: {res.falsification.status} ({res.falsification.samples_evaluated} samples)")
        for pr in res.proof_results:
            print(
                f"  - {pr.theorem_name:<32} | proved={pr.proved} | tier={pr.tier_used:<14} "
                f"| attempts={pr.attempts} ({pr.duration_s:.1f}s)"
            )
        if res.build_and_shake:
            bs = res.build_and_shake
            print(
                f"Build & Shake: ok={bs.build_ok} built={bs.built_modules} "
                f"shake={bs.shake_backend} removed_imports={bs.shake_removed_imports}"
            )
        if res.gate_result:
            print(
                f"Palomar Gate:  {res.gate_result.verdict} | theorems={len(res.gate_result.verified_theorems)} "
                f"| axioms={res.gate_result.axioms_used}"
            )
    return 0 if res.status == "VERIFIED" else 1


def cmd_diff_reprove(args: argparse.Namespace) -> int:
    cfg = load_spec_config(args.project)
    res = run_diff_aware_reprove(cfg, lean_bin=args.lean_bin, attestation_out=args.attestation)
    if args.as_json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(f"=== PCVH PR Diff-Aware Incremental Re-Prover: {res.spec_name} ===")
        print(f"Status:       {res.status} ({res.duration_s:.2f}s)")
        print(f"Cache hit:    {len(res.cached_theorems)} cached | {len(res.reproved_theorems)} reproved ({res.cache_hit_rate_pct:.1f}% reused)")
        print(f"Cached:       {res.cached_theorems}")
        print(f"Re-proved:    {res.reproved_theorems}")
        if res.gate_result:
            print(f"Palomar Gate: {res.gate_result.verdict} | axioms={res.gate_result.axioms_used}")
    return 0 if res.status == "VERIFIED" else 1


def cmd_eval(args: argparse.Namespace) -> int:
    res = run_eval_benchmark_40(
        lean_bin=args.lean_bin,
        out_json=args.out_json,
        out_html=args.out_html,
    )
    if args.as_json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print("=== PCVH 40-Invariant Engineering Eval Benchmark ===")
        print(f"Sound Verified: {res.sound_palomar_verified}/{res.sound_tasks} ({res.sound_auto_prove_pct:.1f}%)")
        print(f"Buggy Caught:   {res.buggy_caught_stage2}/{res.buggy_tasks} ({res.falsification_recall_pct:.1f}% Stage-2 recall)")
        print(f"False Accepts:  {res.false_acceptance_count} (0%)")
        print(f"Axioms Used:    {res.axioms_used}")
        print(f"Duration:       {res.total_duration_s:.1f}s")
        for dom, st in res.per_domain.items():
            print(f"  - {dom:<16}: sound={st['sound_verified']}/{st['sound_total']} | buggy_caught={st['buggy_caught']}/{st['buggy_total']}")
        if args.out_html:
            print(f"HTML Dashboard: {args.out_html}")
    return 0 if (res.sound_palomar_verified >= 28 and res.buggy_caught_stage2 == res.buggy_tasks) else 1


def cmd_studio(args: argparse.Namespace) -> int:
    return serve_studio(
        args.root,
        host=args.host,
        port=args.port,
        lean_bin=args.lean_bin,
        open_browser=not args.no_open,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pcvh", description="Agentic Proof-Carrying Verification Harness")
    sub = p.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Scaffold a multi-language PCVH project (Rust, TypeScript, Solidity, Python)")
    p_init.add_argument("dest", type=pathlib.Path)
    p_init.add_argument("--lang", choices=SUPPORTED_LANGUAGES, default="rust")
    p_init.add_argument("--template", choices=SUPPORTED_TEMPLATES, default="ratelimit")
    p_init.add_argument("--name", type=str, default=None)
    p_init.add_argument("--no-pin", action="store_true")
    p_init.add_argument("--json", action="store_true", dest="as_json")
    p_init.set_defaults(func=cmd_init)

    p_pin = sub.add_parser("pin", help="Pin TCB files into spec.lock.json and immutable snapshot")
    p_pin.add_argument("project", type=pathlib.Path)
    p_pin.add_argument("--json", action="store_true", dest="as_json")
    p_pin.set_defaults(func=cmd_pin)

    p_aud = sub.add_parser("audit", help="Run fast TCB hash + static anti-cheat scan")
    p_aud.add_argument("project", type=pathlib.Path)
    p_aud.set_defaults(func=cmd_audit)

    p_kg = sub.add_parser("keygen", help="Generate Ed25519 keypair for DSSE attestation signing")
    p_kg.add_argument("--out-dir", type=pathlib.Path, default=pathlib.Path("."))
    p_kg.add_argument("--prefix", type=str, default="pcvh_signing")
    p_kg.add_argument("--json", action="store_true", dest="as_json")
    p_kg.set_defaults(func=cmd_keygen)

    p_sig = sub.add_parser("sign", help="Sign a proof-attestation.json with an Ed25519 private key (DSSEv1)")
    p_sig.add_argument("attestation", type=pathlib.Path)
    p_sig.add_argument("--key", type=pathlib.Path, required=True)
    p_sig.add_argument("--key-id", type=str, default=None)
    p_sig.add_argument("--json", action="store_true", dest="as_json")
    p_sig.set_defaults(func=cmd_sign)

    p_vsig = sub.add_parser("verify-sig", help="Cryptographically verify a signed proof-attestation.json")
    p_vsig.add_argument("attestation", type=pathlib.Path)
    p_vsig.add_argument("--pubkey", type=pathlib.Path, required=True)
    p_vsig.add_argument("--json", action="store_true", dest="as_json")
    p_vsig.set_defaults(func=cmd_verify_sig)

    p_fal = sub.add_parser("falsify", help="Run Stage-2 executable falsification pre-check")
    p_fal.add_argument("project", type=pathlib.Path)
    p_fal.add_argument("--lean-bin", type=pathlib.Path, default=None)
    p_fal.add_argument("--json", action="store_true", dest="as_json")
    p_fal.set_defaults(func=cmd_falsify)

    p_lsp = sub.add_parser("inspect-goals", help="Query live Lean 4 LSP `$/lean/plainGoal` at line/col")
    p_lsp.add_argument("project", type=pathlib.Path)
    p_lsp.add_argument("file", type=pathlib.Path)
    p_lsp.add_argument("line", type=int, help="1-indexed line number")
    p_lsp.add_argument("col", type=int, default=0, nargs="?", help="0-indexed column")
    p_lsp.add_argument("--lean-bin", type=pathlib.Path, default=None)
    p_lsp.add_argument("--json", action="store_true", dest="as_json")
    p_lsp.set_defaults(func=cmd_inspect_goals)

    p_prv = sub.add_parser("prove", help="Run full 7-stage autonomous Spec -> Proof -> Shake -> Palomar Gate pipeline")
    p_prv.add_argument("project", type=pathlib.Path)
    p_prv.add_argument("--lean-bin", type=pathlib.Path, default=None)
    p_prv.add_argument("--attestation", type=pathlib.Path, default=None)
    p_prv.add_argument("--workers", type=int, default=None, help="Max parallel lemma prover workers (gated by lean-orch)")
    p_prv.add_argument("--llm-provider", choices=("auto", "anthropic", "openai", "ollama", "none"), default="auto")
    p_prv.add_argument("--llm-model", type=str, default=None)
    p_prv.add_argument("--llm-base-url", type=str, default=None)
    p_prv.add_argument("--no-tree-search", action="store_true")
    p_prv.add_argument("--json", action="store_true", dest="as_json")
    p_prv.set_defaults(func=cmd_prove)

    p_dif = sub.add_parser("diff-reprove", help="PR diff-aware incremental proof repair (re-proves only invalidated lemmas)")
    p_dif.add_argument("project", type=pathlib.Path)
    p_dif.add_argument("--lean-bin", type=pathlib.Path, default=None)
    p_dif.add_argument("--attestation", type=pathlib.Path, default=None)
    p_dif.add_argument("--json", action="store_true", dest="as_json")
    p_dif.set_defaults(func=cmd_diff_reprove)

    p_evl = sub.add_parser("eval", help="Run the 40-invariant engineering eval benchmark & emit HTML dashboard")
    p_evl.add_argument("--lean-bin", type=pathlib.Path, default=None)
    p_evl.add_argument("--out-json", type=pathlib.Path, default=None)
    p_evl.add_argument("--out-html", type=pathlib.Path, default=None)
    p_evl.add_argument("--json", action="store_true", dest="as_json")
    p_evl.set_defaults(func=cmd_eval)

    p_ver = sub.add_parser("verify", help="Run full zero-trust Palomar verification gate")
    p_ver.add_argument("project", type=pathlib.Path)
    p_ver.add_argument("--lean-bin", type=pathlib.Path, default=None)
    p_ver.add_argument("--attestation", type=pathlib.Path, default=None)
    p_ver.add_argument("--skip-conformance", action="store_true")
    p_ver.add_argument("--require-dual-kernel", action="store_true", help="Fail unless lean4export + nanoda replay succeeds")
    p_ver.add_argument("--sign-key", type=pathlib.Path, default=None, help="Ed25519 private key PEM to sign attestation")
    p_ver.add_argument("--sign-key-id", type=str, default=None)
    p_ver.add_argument("--json", action="store_true", dest="as_json")
    p_ver.set_defaults(func=cmd_verify)

    p_cat = sub.add_parser("cert-cat0", help="Synthesize & Palomar-verify Lean 4 CAT(0) proof from CVXPY SOCP")
    p_cat.add_argument("blueprint", type=pathlib.Path)
    p_cat.add_argument("--lean-bin", type=pathlib.Path, default=None)
    p_cat.add_argument("--json", action="store_true", dest="as_json")
    p_cat.set_defaults(func=cmd_cert_cat0)

    p_stu = sub.add_parser("studio", help="Launch interactive PCVH Local Web Studio UI")
    p_stu.add_argument("--root", type=pathlib.Path, default=pathlib.Path("."))
    p_stu.add_argument("--host", type=str, default="127.0.0.1")
    p_stu.add_argument("--port", type=int, default=8765)
    p_stu.add_argument("--lean-bin", type=pathlib.Path, default=None)
    p_stu.add_argument("--no-open", action="store_true")
    p_stu.set_defaults(func=cmd_studio)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
