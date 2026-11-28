"""Direct runtime bridge between PCVH and `lean-build-orchestrator` (`lean-orch`)."""

from __future__ import annotations

from dataclasses import dataclass
import pathlib
import sys
from typing import Dict, List, Optional, Sequence


def _import_lean_orch():
    orch_root = pathlib.Path(__file__).resolve().parents[3] / "lean-build-orchestrator"
    if orch_root.exists() and str(orch_root) not in sys.path:
        sys.path.insert(0, str(orch_root))
    from lean_orch.dag import analyze_project
    from lean_orch.memory import get_memory_snapshot
    from lean_orch.scheduler import CommitAwareScheduler, SchedulerConfig
    from lean_orch.shaker import run_lake_shake
    return analyze_project, get_memory_snapshot, CommitAwareScheduler, SchedulerConfig, run_lake_shake


@dataclass
class BuildAndShakeReport:
    build_ok: bool
    built_modules: int
    cached_modules: int
    failed_modules: List[str]
    wall_time_s: float
    shake_backend: str
    shake_files_modified: int
    shake_removed_imports: int
    shake_rolled_back: List[str]
    commit_avail_gb: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "build_ok": self.build_ok,
            "built_modules": self.built_modules,
            "cached_modules": self.cached_modules,
            "failed_modules": list(self.failed_modules),
            "wall_time_s": round(self.wall_time_s, 2),
            "shake_backend": self.shake_backend,
            "shake_files_modified": self.shake_files_modified,
            "shake_removed_imports": self.shake_removed_imports,
            "shake_rolled_back": list(self.shake_rolled_back),
            "commit_avail_gb": round(self.commit_avail_gb, 2),
        }


def build_and_shake_project(
    project_root: pathlib.Path,
    targets: Optional[Sequence[str]] = None,
    *,
    lean_bin: Optional[pathlib.Path] = None,
    run_shake: bool = True,
    max_workers: int = 2,
    reserve_commit_gb: float = 3.0,
) -> BuildAndShakeReport:
    """Build project using `lean-orch` commit-charge scheduler, then run Stage-6 `lake shake` with rollback safety."""
    analyze_project, get_memory_snapshot, CommitAwareScheduler, SchedulerConfig, run_lake_shake = _import_lean_orch()
    snap = get_memory_snapshot()
    dag = analyze_project(project_root)

    # Cap concurrency safely if commit headroom is tight (e.g., while a heavy background Mathlib build runs)
    safe_workers = 1 if snap.commit_avail_gb < 14.0 else max_workers
    cfg = SchedulerConfig(
        reserve_commit_gb=reserve_commit_gb,
        max_workers=safe_workers,
        poll_interval_s=0.1,
        lean_bin=lean_bin,
    )
    build_res = CommitAwareScheduler(dag, cfg).run(targets)

    if build_res.failed_modules or not run_shake:
        return BuildAndShakeReport(
            build_ok=(len(build_res.failed_modules) == 0),
            built_modules=build_res.built_modules,
            cached_modules=build_res.cached_modules,
            failed_modules=list(build_res.failed_modules),
            wall_time_s=build_res.wall_time_s,
            shake_backend="skipped",
            shake_files_modified=0,
            shake_removed_imports=0,
            shake_rolled_back=[],
            commit_avail_gb=snap.commit_avail_gb,
        )

    fresh_dag = analyze_project(project_root)
    shake_res = run_lake_shake(
        fresh_dag,
        targets,
        apply_fix=True,
        verify_after_fix=True,
        lean_bin=lean_bin,
        scheduler_config=cfg,
    )
    return BuildAndShakeReport(
        build_ok=(not build_res.failed_modules and shake_res.returncode == 0),
        built_modules=build_res.built_modules,
        cached_modules=build_res.cached_modules,
        failed_modules=list(build_res.failed_modules),
        wall_time_s=build_res.wall_time_s,
        shake_backend=shake_res.backend,
        shake_files_modified=len(shake_res.edits),
        shake_removed_imports=sum(len(e.remove_imports) for e in shake_res.edits),
        shake_rolled_back=list(shake_res.rolled_back_files),
        commit_avail_gb=snap.commit_avail_gb,
    )
