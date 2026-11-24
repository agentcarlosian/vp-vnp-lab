"""End-to-End 7-Stage Autonomous Spec -> Falsify -> Plan -> Prove -> Build -> Shake -> Palomar Gate Orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import pathlib
import time
from typing import Dict, List, Optional

from ..config import SpecConfig
from ..falsify.falsifier import FalsificationResult, run_falsification_precheck
from ..runtime.build_bridge import BuildAndShakeReport, build_and_shake_project
from ..tcb.manifest import LOCK_FILENAME, pin_tcb_manifest, verify_tcb_manifest
from ..tcb.palomar_gate import GateResult, _run_with_transient_oom_retry, resolve_lean_bin, run_palomar_gate
from .planner import ProofPlan, build_proof_plan, render_solution_aggregator
from .prover import IterativeProverWorker, LLMBackend, TaskProofResult
from .retriever import PremiseEntry, build_premise_index_from_modules


@dataclass
class ProvePipelineResult:
    status: str  # "VERIFIED" | "REFUTED_BY_FALSIFIER" | "PROVER_INCOMPLETE" | "BUILD_FAILED" | "GATE_REJECTED"
    spec_name: str
    duration_s: float
    falsification: FalsificationResult
    plan: Optional[ProofPlan] = None
    proof_results: List[TaskProofResult] = field(default_factory=list)
    build_and_shake: Optional[BuildAndShakeReport] = None
    gate_result: Optional[GateResult] = None
    total_cost_usd: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "status": self.status,
            "spec_name": self.spec_name,
            "duration_s": round(self.duration_s, 3),
            "total_cost_usd": round(self.total_cost_usd, 4),
            "falsification": self.falsification.to_dict(),
            "plan": self.plan.to_dict() if self.plan else None,
            "proofs": [
                {
                    "theorem": r.theorem_name,
                    "module": r.module_name,
                    "proved": r.proved,
                    "tier_used": r.tier_used,
                    "attempts": r.attempts,
                    "llm_rounds": r.llm_rounds,
                    "duration_s": round(r.duration_s, 2),
                }
                for r in self.proof_results
            ],
            "build_and_shake": self.build_and_shake.to_dict() if self.build_and_shake else None,
            "gate_verdict": self.gate_result.verdict if self.gate_result else None,
            "verified_theorems": self.gate_result.verified_theorems if self.gate_result else [],
            "axioms_used": self.gate_result.axioms_used if self.gate_result else [],
        }


def run_autonomous_prove_pipeline(
    cfg: SpecConfig,
    *,
    lean_bin: Optional[pathlib.Path] = None,
    llm_backend: Optional[LLMBackend] = None,
    skip_symbolic_tiers: bool = False,
    auto_pin_if_missing: bool = True,
    attestation_out: Optional[pathlib.Path] = None,
) -> ProvePipelineResult:
    """Execute the full 7-stage autonomous Spec -> Proof -> Shake -> Palomar Gate pipeline."""
    t0 = time.time()

    # Stage 1: TCB Freeze / Pin
    if not (cfg.project_root / LOCK_FILENAME).exists():
        if auto_pin_if_missing:
            pin_tcb_manifest(cfg, save_snapshot=True)
    man = verify_tcb_manifest(cfg)
    if not man.ok:
        raise RuntimeError(f"TCB integrity check failed before proving: mismatched={man.mismatched_files}")

    # Stage 2: Executable Falsification Pre-Check (Fail Fast on Buggy Specs!)
    fals_res = run_falsification_precheck(cfg, lean_bin=lean_bin)
    if not fals_res.ok:
        return ProvePipelineResult(
            status="REFUTED_BY_FALSIFIER",
            spec_name=cfg.name,
            duration_s=time.time() - t0,
            falsification=fals_res,
        )

    # Stage 3: Lemma DAG Decomposition & Premise Index Construction
    plan = build_proof_plan(cfg)

    # Ensure Statement .olean is built so prover & premise retriever can reflect it immediately
    lean_bin_dir = resolve_lean_bin(cfg.project_root, lean_bin)
    lake_exe = lean_bin_dir / ("lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = str(lean_bin_dir) + os.pathsep + env.get("PATH", "")
    _run_with_transient_oom_retry(
        [str(lake_exe), "build", plan.statement_module],
        cwd=cfg.project_root,
        env=env,
    )

    premise_index = build_premise_index_from_modules(
        cfg.project_root,
        [plan.statement_module],
        lean_bin=lean_bin,
    )

    # Stage 4: Iterative Prover Loop over topological Lemma DAG
    worker = IterativeProverWorker(
        cfg,
        plan,
        premise_index,
        lean_bin=lean_bin,
        llm_backend=llm_backend,
        skip_symbolic_tiers=skip_symbolic_tiers,
    )

    proved_modules: Dict[str, str] = {}
    proof_results: List[TaskProofResult] = []

    for task in plan.tasks:
        res = worker.prove_task(task, proved_modules)
        proof_results.append(res)
        if res.proved:
            proved_modules[task.name] = task.module_name
            # Compile the proved lemma module so downstream lemmas & premise index can import it
            _run_with_transient_oom_retry(
                [str(lake_exe), "build", task.module_name],
                cwd=cfg.project_root,
                env=env,
            )
            premise_index.add(
                PremiseEntry(
                    name=f"PCVHProofs.{task.name}",
                    short_name=task.name,
                    kind="theorem",
                    signature=task.theorem.raw_signature,
                    module=task.module_name,
                )
            )

    if len(proved_modules) < len(plan.tasks):
        return ProvePipelineResult(
            status="PROVER_INCOMPLETE",
            spec_name=cfg.name,
            duration_s=time.time() - t0,
            falsification=fals_res,
            plan=plan,
            proof_results=proof_results,
            total_cost_usd=worker.spent_usd,
        )

    # Assemble root `Solution.lean` re-exporting all proved theorems into `namespace Solution`
    sol_src = render_solution_aggregator(plan, proved_modules)
    (cfg.project_root / f"{cfg.solution_module}.lean").write_text(sol_src, encoding="utf-8")

    # Stage 5 & 6: Commit-Aware `lean-orch` Build + Automated `lake shake` Import Minimization
    bs_report = build_and_shake_project(
        cfg.project_root,
        targets=[cfg.solution_module],
        lean_bin=lean_bin,
        run_shake=cfg.auto_lake_shake,
    )
    if not bs_report.build_ok:
        return ProvePipelineResult(
            status="BUILD_FAILED",
            spec_name=cfg.name,
            duration_s=time.time() - t0,
            falsification=fals_res,
            plan=plan,
            proof_results=proof_results,
            build_and_shake=bs_report,
            total_cost_usd=worker.spent_usd,
        )

    # Stage 7: Zero-Trust Palomar Verification Gate (Zone C)
    att_path = attestation_out or (cfg.project_root / "proof-attestation.json")
    gate_res = run_palomar_gate(
        cfg,
        lean_bin=lean_bin,
        run_conformance=True,
        attestation_out=att_path,
    )

    return ProvePipelineResult(
        status="VERIFIED" if gate_res.verdict == "VERIFIED" else "GATE_REJECTED",
        spec_name=cfg.name,
        duration_s=time.time() - t0,
        falsification=fals_res,
        plan=plan,
        proof_results=proof_results,
        build_and_shake=bs_report,
        gate_result=gate_res,
        total_cost_usd=worker.spent_usd,
    )
