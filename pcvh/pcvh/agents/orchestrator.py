"""End-to-End 7-Stage Autonomous Spec -> Falsify -> Plan -> Prove -> Build -> Shake -> Palomar Gate Orchestrator."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import os
import pathlib
import sys
import time
from typing import Dict, List, Optional

from ..config import SpecConfig
from ..falsify.falsifier import FalsificationResult, run_falsification_precheck
from ..runtime.build_bridge import BuildAndShakeReport, build_and_shake_project
from ..tcb.manifest import LOCK_FILENAME, pin_tcb_manifest, verify_tcb_manifest
from ..tcb.palomar_gate import GateResult, _run_with_transient_oom_retry, resolve_lean_bin, run_palomar_gate
from .llm_providers import create_llm_backend
from .planner import LemmaTask, ProofPlan, build_proof_plan, render_solution_aggregator
from .prover import IterativeProverWorker, LLMBackend, TaskProofResult
from .retriever import PremiseEntry, build_premise_index_from_modules
from .tree_search import TreeSearchConfig


def compute_commit_gated_workers(requested_workers: int, *, per_worker_gb: float = 2.0, reserve_gb: float = 3.0) -> tuple[int, float]:
    """Query `lean-orch` live commit-charge telemetry to safely cap parallel Lean prover workers."""
    req = max(1, int(requested_workers))
    try:
        orch_root = pathlib.Path(__file__).resolve().parents[3] / "lean-build-orchestrator"
        if orch_root.exists() and str(orch_root) not in sys.path:
            sys.path.insert(0, str(orch_root))
        from lean_orch.memory import estimate_safe_workers, get_memory_snapshot

        snap = get_memory_snapshot()
        safe = estimate_safe_workers(
            avail_commit_gb=snap.commit_avail_gb,
            per_worker_gb=per_worker_gb,
            reserve_gb=reserve_gb,
            max_cap=req,
        )
        return max(1, min(req, safe)), snap.commit_avail_gb
    except Exception:
        return req, -1.0


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
    waves_executed: int = 0
    peak_parallel_workers: int = 1

    def to_dict(self) -> Dict[str, object]:
        return {
            "status": self.status,
            "spec_name": self.spec_name,
            "duration_s": round(self.duration_s, 3),
            "total_cost_usd": round(self.total_cost_usd, 4),
            "waves_executed": self.waves_executed,
            "peak_parallel_workers": self.peak_parallel_workers,
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
                    "tree_search_stats": r.tree_search_stats,
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
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
    llm_base_url: Optional[str] = None,
    skip_symbolic_tiers: bool = False,
    enable_tree_search: Optional[bool] = None,
    tree_search_config: Optional[TreeSearchConfig] = None,
    parallel_workers: Optional[int] = None,
    auto_pin_if_missing: bool = True,
    attestation_out: Optional[pathlib.Path] = None,
) -> ProvePipelineResult:
    """Execute the full 7-stage autonomous Spec -> Proof -> Shake -> Palomar Gate pipeline."""
    t0 = time.time()

    if llm_backend is None and llm_provider:
        llm_backend = create_llm_backend(llm_provider, model=llm_model, base_url=llm_base_url)

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

    # Stage 4: Commit-Gated Parallel Topological Wave Prover Loop
    worker = IterativeProverWorker(
        cfg,
        plan,
        premise_index,
        lean_bin=lean_bin,
        llm_backend=llm_backend,
        skip_symbolic_tiers=skip_symbolic_tiers,
        enable_tree_search=enable_tree_search,
        tree_search_config=tree_search_config,
    )

    req_workers = parallel_workers if parallel_workers is not None else cfg.max_parallel_workers
    proved_modules: Dict[str, str] = {}
    proof_results_by_name: Dict[str, TaskProofResult] = {}
    remaining: List[LemmaTask] = list(plan.tasks)
    failed_names: set[str] = set()
    waves_executed = 0
    peak_parallel = 1

    while remaining:
        ready = [
            t for t in remaining
            if all(d in proved_modules for d in t.depends_on)
        ]
        if not ready:
            # Upstream dependencies failed; run remaining tasks best-effort so partial diagnostics are reported
            ready = [remaining[0]]

        remaining = [t for t in remaining if t not in ready]
        waves_executed += 1
        allowed_workers, _ = compute_commit_gated_workers(min(req_workers, len(ready)))
        peak_parallel = max(peak_parallel, min(allowed_workers, len(ready)))

        snapshot_proved = dict(proved_modules)
        wave_results: List[TaskProofResult] = []
        if allowed_workers <= 1 or len(ready) <= 1:
            for t in ready:
                wave_results.append(worker.prove_task(t, snapshot_proved))
        else:
            with ThreadPoolExecutor(max_workers=allowed_workers) as pool:
                fut_map = {pool.submit(worker.prove_task, t, snapshot_proved): t for t in ready}
                for fut in as_completed(fut_map):
                    wave_results.append(fut.result())

        newly_proved_mods: List[str] = []
        task_by_name = {t.name: t for t in ready}
        for res in wave_results:
            proof_results_by_name[res.theorem_name] = res
            if res.proved:
                proved_modules[res.theorem_name] = res.module_name
                newly_proved_mods.append(res.module_name)
                t_obj = task_by_name[res.theorem_name]
                premise_index.add(
                    PremiseEntry(
                        name=f"PCVHProofs.{t_obj.name}",
                        short_name=t_obj.name,
                        kind="theorem",
                        signature=t_obj.theorem.raw_signature,
                        module=t_obj.module_name,
                    )
                )
            else:
                failed_names.add(res.theorem_name)

        # Compile all newly proved lemma modules from this wave so downstream waves can import them
        if newly_proved_mods and remaining:
            _run_with_transient_oom_retry(
                [str(lake_exe), "build", *newly_proved_mods],
                cwd=cfg.project_root,
                env=env,
            )

    proof_results = [proof_results_by_name[t.name] for t in plan.tasks if t.name in proof_results_by_name]

    if len(proved_modules) < len(plan.tasks):
        return ProvePipelineResult(
            status="PROVER_INCOMPLETE",
            spec_name=cfg.name,
            duration_s=time.time() - t0,
            falsification=fals_res,
            plan=plan,
            proof_results=proof_results,
            total_cost_usd=worker.spent_usd,
            waves_executed=waves_executed,
            peak_parallel_workers=peak_parallel,
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
            waves_executed=waves_executed,
            peak_parallel_workers=peak_parallel,
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
        waves_executed=waves_executed,
        peak_parallel_workers=peak_parallel,
    )
