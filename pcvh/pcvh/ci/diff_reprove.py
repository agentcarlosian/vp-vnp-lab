"""PR Diff-Aware Incremental Proof Repair Engine (`pcvh diff-reprove`).

Hashes per-definition Statement bodies (transitively across the call graph) and per-theorem
Challenge signatures into `.pcvh_diff_cache.json`. On subsequent spec/code edits, only
theorems whose signature or transitive Statement dependencies changed are re-synthesized;
unaffected lemmas reuse their previously verified `Solution/Lem_*.lean` modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
import pathlib
import re
import time
from typing import Dict, List, Optional, Set

from ..agents.planner import build_proof_plan, render_solution_aggregator
from ..agents.prover import IterativeProverWorker, LLMBackend, TaskProofResult
from ..agents.retriever import PremiseEntry, build_premise_index_from_modules
from ..config import SpecConfig
from ..falsify.falsifier import FalsificationResult, run_falsification_precheck
from ..runtime.build_bridge import BuildAndShakeReport, build_and_shake_project
from ..tcb.manifest import pin_tcb_manifest
from ..tcb.palomar_gate import GateResult, _run_with_transient_oom_retry, resolve_lean_bin, run_palomar_gate
from ..tcb.static_audit import strip_lean_comments_and_strings

DIFF_CACHE_FILENAME = ".pcvh_diff_cache.json"

_DECL_START_RE = re.compile(
    r"^\s*(?:private\s+|protected\s+|noncomputable\s+)*(?:def|abbrev|structure|inductive)\s+([A-Za-z_][A-Za-z0-9_']*)\b",
    re.MULTILINE,
)


def _sha256_text(s: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", s.strip()).encode("utf-8")).hexdigest()


def compute_statement_transitive_hashes(stmt_path: pathlib.Path) -> Dict[str, str]:
    """Compute a transitive SHA-256 fingerprint for every declaration in `Statement.lean`."""
    cleaned = strip_lean_comments_and_strings(stmt_path.read_text(encoding="utf-8", errors="replace"))
    matches = list(_DECL_START_RE.finditer(cleaned))
    spans: Dict[str, str] = {}
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned)
        chunk = cleaned[start:end]
        # Exclude trailing `end <Namespace>` closers so adding a new sibling def below doesn't shift the hash!
        chunk = re.sub(r"^\s*end\s+[A-Za-z0-9_.']+\s*$", "", chunk, flags=re.MULTILINE)
        spans[m.group(1)] = chunk

    names = set(spans.keys())
    deps: Dict[str, Set[str]] = {}
    for name, body in spans.items():
        deps[name] = {other for other in names if other != name and re.search(rf"\b{re.escape(other)}\b", body)}

    def closure(root: str) -> Set[str]:
        seen: Set[str] = set()
        stack = [root]
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            stack.extend(deps.get(u, ()))
        return seen

    out: Dict[str, str] = {}
    for name in spans:
        parts = [f"{d}:{_sha256_text(spans[d])}" for d in sorted(closure(name))]
        out[name] = _sha256_text("|".join(parts))
    return out


@dataclass
class DiffReproveReport:
    status: str  # "VERIFIED" | "REFUTED_BY_FALSIFIER" | "PROVER_INCOMPLETE" | "GATE_REJECTED"
    spec_name: str
    cached_theorems: List[str] = field(default_factory=list)
    reproved_theorems: List[str] = field(default_factory=list)
    removed_theorems: List[str] = field(default_factory=list)
    duration_s: float = 0.0
    falsification: Optional[FalsificationResult] = None
    proof_results: List[TaskProofResult] = field(default_factory=list)
    build_and_shake: Optional[BuildAndShakeReport] = None
    gate_result: Optional[GateResult] = None

    @property
    def cache_hit_rate_pct(self) -> float:
        tot = len(self.cached_theorems) + len(self.reproved_theorems)
        return 100.0 * len(self.cached_theorems) / max(1, tot)

    def to_dict(self) -> Dict[str, object]:
        return {
            "status": self.status,
            "spec_name": self.spec_name,
            "cached_theorems": list(self.cached_theorems),
            "reproved_theorems": list(self.reproved_theorems),
            "removed_theorems": list(self.removed_theorems),
            "cache_hit_rate_pct": round(self.cache_hit_rate_pct, 1),
            "duration_s": round(self.duration_s, 3),
            "gate_verdict": self.gate_result.verdict if self.gate_result else None,
            "verified_theorems": self.gate_result.verified_theorems if self.gate_result else [],
        }


def run_diff_aware_reprove(
    cfg: SpecConfig,
    *,
    lean_bin: Optional[pathlib.Path] = None,
    llm_backend: Optional[LLMBackend] = None,
    attestation_out: Optional[pathlib.Path] = None,
) -> DiffReproveReport:
    """Incrementally re-prove ONLY theorems affected by edits to Statement.lean / Challenge.lean."""
    t0 = time.time()

    # 1. Re-pin updated TCB snapshot & manifest for the PR revision
    pin_tcb_manifest(cfg, save_snapshot=True)

    # 2. Stage-2 falsification pre-check on updated spec
    fals_res = run_falsification_precheck(cfg, lean_bin=lean_bin)
    if not fals_res.ok:
        return DiffReproveReport(
            status="REFUTED_BY_FALSIFIER",
            spec_name=cfg.name,
            duration_s=time.time() - t0,
            falsification=fals_res,
        )

    plan = build_proof_plan(cfg)
    stmt_hashes = compute_statement_transitive_hashes(cfg.project_root / cfg.statement_rel)
    cache_fp = cfg.project_root / DIFF_CACHE_FILENAME
    prev_cache = json.loads(cache_fp.read_text(encoding="utf-8")) if cache_fp.exists() else {}
    prev_thms: Dict[str, Dict[str, str]] = prev_cache.get("theorems", {})

    # Compute current per-theorem composite fingerprint (exact signature + referenced Statement transitive hashes)
    cur_fingerprints: Dict[str, str] = {}
    for task in plan.tasks:
        sig_h = _sha256_text(task.theorem.raw_signature)
        ref_defs = sorted(
            d for d in stmt_hashes if re.search(rf"\b{re.escape(d)}\b", task.theorem.raw_signature)
        )
        dep_h = _sha256_text("|".join(f"{d}:{stmt_hashes[d]}" for d in ref_defs))
        cur_fingerprints[task.name] = _sha256_text(f"{sig_h}|{dep_h}")

    # Determine which lemmas can be safely reused from cache vs must be re-proved
    cached: List[str] = []
    invalidated: Set[str] = set()
    for task in plan.tasks:
        lem_fp = cfg.project_root / task.rel_file_path
        prev_entry = prev_thms.get(task.name)
        upstream_invalid = any(d in invalidated for d in task.depends_on)
        if (
            prev_entry is not None
            and prev_entry.get("fingerprint") == cur_fingerprints[task.name]
            and lem_fp.exists()
            and not upstream_invalid
        ):
            cached.append(task.name)
        else:
            invalidated.add(task.name)

    cur_names = {t.name for t in plan.tasks}
    removed = sorted(set(prev_thms.keys()) - cur_names)
    for rem_name in removed:
        rem_mod = prev_thms.get(rem_name, {}).get("module", "")
        if rem_mod:
            rem_fp = cfg.project_root / (rem_mod.replace(".", "/") + ".lean")
            rem_fp.unlink(missing_ok=True)

    # Ensure Statement .olean is fresh
    lean_bin_dir = resolve_lean_bin(cfg.project_root, lean_bin)
    lake_exe = lean_bin_dir / ("lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = str(lean_bin_dir) + os.pathsep + env.get("PATH", "")
    _run_with_transient_oom_retry([str(lake_exe), "build", plan.statement_module], cwd=cfg.project_root, env=env)

    premise_index = build_premise_index_from_modules(cfg.project_root, [plan.statement_module], lean_bin=lean_bin)
    worker = IterativeProverWorker(cfg, plan, premise_index, lean_bin=lean_bin, llm_backend=llm_backend)

    proved_modules: Dict[str, str] = {}
    proof_results: List[TaskProofResult] = []
    reproved: List[str] = []

    for task in plan.tasks:
        if task.name in cached:
            proved_modules[task.name] = task.module_name
            premise_index.add(
                PremiseEntry(f"PCVHProofs.{task.name}", task.name, "theorem", task.theorem.raw_signature, task.module_name)
            )
            continue

        reproved.append(task.name)
        res = worker.prove_task(task, proved_modules)
        proof_results.append(res)
        if res.proved:
            proved_modules[task.name] = task.module_name
            _run_with_transient_oom_retry([str(lake_exe), "build", task.module_name], cwd=cfg.project_root, env=env)
            premise_index.add(
                PremiseEntry(f"PCVHProofs.{task.name}", task.name, "theorem", task.theorem.raw_signature, task.module_name)
            )

    if len(proved_modules) < len(plan.tasks):
        return DiffReproveReport(
            status="PROVER_INCOMPLETE",
            spec_name=cfg.name,
            cached_theorems=cached,
            reproved_theorems=reproved,
            removed_theorems=removed,
            duration_s=time.time() - t0,
            falsification=fals_res,
            proof_results=proof_results,
        )

    # Assemble updated Solution.lean, build via lean-orch, and run Zero-Trust Palomar Gate
    sol_src = render_solution_aggregator(plan, proved_modules)
    (cfg.project_root / f"{cfg.solution_module}.lean").write_text(sol_src, encoding="utf-8")

    bs_report = build_and_shake_project(
        cfg.project_root,
        targets=[cfg.solution_module],
        lean_bin=lean_bin,
        run_shake=False,  # preserve incremental lemma imports cleanly
    )
    att_path = attestation_out or (cfg.project_root / "proof-attestation.json")
    gate_res = run_palomar_gate(cfg, trusted_local=True, lean_bin=lean_bin, run_conformance=True, attestation_out=att_path)

    if gate_res.verdict == "VERIFIED":
        cache_fp.write_text(
            json.dumps(
                {
                    "schema": "pcvh.diff-cache.v1",
                    "theorems": {
                        t.name: {"fingerprint": cur_fingerprints[t.name], "module": t.module_name}
                        for t in plan.tasks
                    },
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    return DiffReproveReport(
        status="VERIFIED" if gate_res.verdict == "VERIFIED" else "GATE_REJECTED",
        spec_name=cfg.name,
        cached_theorems=cached,
        reproved_theorems=reproved,
        removed_theorems=removed,
        duration_s=time.time() - t0,
        falsification=fals_res,
        proof_results=proof_results,
        build_and_shake=bs_report,
        gate_result=gate_res,
    )
