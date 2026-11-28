"""Command-line interface for lean-build-orchestrator (`lean-orch`)."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import List, Optional

from .dag import analyze_project, discover_default_targets
from .memory import get_memory_snapshot
from .scheduler import CommitAwareScheduler, SchedulerConfig
from .shaker import run_lake_shake


def _common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("project", type=pathlib.Path, help="Path to Lean 4 Lake project root")
    p.add_argument("--lean-bin", type=pathlib.Path, default=None, help="Directory containing lake/lean binaries")
    p.add_argument("--heavy-gb", type=float, default=None, help="Override commit GB weight for umbrella-importing modules")
    p.add_argument("--reserve-gb", type=float, default=3.0, help="Commit-charge safety margin in GB (default: 3.0)")
    p.add_argument("--max-workers", type=int, default=8, help="Upper bound on concurrent Lake workers (default: 8)")
    p.add_argument("--json", action="store_true", dest="as_json", help="Emit structured JSON output")


def cmd_audit(args: argparse.Namespace) -> int:
    snap = get_memory_snapshot()
    dag = analyze_project(args.project, heavy_worker_gb=args.heavy_gb)
    targets = args.targets or discover_default_targets(dag.project_root, set(dag.nodes))
    summary = dag.summary_dict(targets)
    offenders = dag.umbrella_blast_radius()
    sched = CommitAwareScheduler(
        dag,
        SchedulerConfig(
            reserve_commit_gb=args.reserve_gb,
            max_workers=args.max_workers,
            lean_bin=args.lean_bin,
        ),
    )
    plan = sched.simulate_plan(targets)

    payload = {
        "memory": snap.to_dict(),
        "targets": targets,
        "summary": summary,
        "plan": plan,
        "top_umbrella_offenders": [
            {
                "module": r.module,
                "direct_umbrellas": r.direct_umbrellas,
                "downstream_poisoned": r.downstream_poisoned_count,
                "exclusive_unlock": r.exclusively_poisoned_count,
            }
            for r in offenders[: args.top]
        ],
    }

    if args.as_json:
        print(json.dumps(payload, indent=2))
        return 0

    print("=== Lean 4 Windows / Low-RAM Build Audit ===")
    print(f"Project:   {dag.project_root}")
    print(f"Toolchain: {dag.toolchain or '<unspecified>'}")
    print(f"Memory:    {snap.format_human()}")
    fp = dag.footprint
    print(
        f"Artifacts: {fp.total_files:,} .olean* files ({fp.total_gb:.2f} GB total, "
        f"{fp.private_gb:.2f} GB .olean.private) -> est. umbrella worker = "
        f"{dag.heavy_worker_gb:.2f} GB commit"
    )
    print(
        f"Modules:   {summary['total_modules']} reachable across {summary['topo_levels']} topo levels "
        f"(fresh={summary['built_fresh']}, remaining={summary['remaining']})"
    )
    print(
        f"Weights:   heavy={summary['heavy_modules']} ({dag.heavy_worker_gb:.1f}GB) | "
        f"medium={summary['medium_modules']} ({dag.medium_worker_gb:.1f}GB) | "
        f"light={summary['light_modules']} ({dag.light_worker_gb:.1f}GB)"
    )
    sc = plan["safe_concurrency"]
    est = plan["estimated_wall_minutes"]
    print(
        f"Safe cap:  heavy={sc['heavy_workers']}x | medium={sc['medium_workers']}x | light={sc['light_workers']}x"
    )
    print(
        f"Est wall:  sequential={est['naive_sequential']}m | "
        f"commit-aware={est['commit_aware_current']}m | "
        f"post-shake={est['post_lake_shake_projected']}m "
        f"({plan['projected_shake_speedup_x']}x projected speedup)"
    )

    if offenders:
        print(f"\nTop {min(args.top, len(offenders))} direct umbrella offenders (out of {len(offenders)}):")
        print(f"  {'Module':<30} | {'Umbrella':<14} | {'Downstream':>10} | {'Exclusive Unlock':>16}")
        print("  " + "-" * 78)
        for r in offenders[: args.top]:
            print(
                f"  {r.module:<30} | {','.join(r.direct_umbrellas):<14} | "
                f"{r.downstream_poisoned_count:>10} | {r.exclusively_poisoned_count:>16}"
            )
    else:
        print("\nNo broad umbrella imports detected — all modules use targeted imports!")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    dag = analyze_project(args.project, heavy_worker_gb=args.heavy_gb)
    targets = args.targets or discover_default_targets(dag.project_root, set(dag.nodes))
    cfg = SchedulerConfig(
        reserve_commit_gb=args.reserve_gb,
        max_workers=args.max_workers,
        max_heavy_workers=args.max_heavy,
        force_rebuild=args.force,
        dry_run=args.dry_run,
        lean_bin=args.lean_bin,
        state_file=args.state_file,
        log_file=args.log_file,
    )
    sched = CommitAwareScheduler(dag, cfg)
    res = sched.run(targets)
    if args.as_json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(
            f"\n[DONE] built={res.built_modules} cached={res.cached_modules} "
            f"failed={len(res.failed_modules)} wall={res.wall_time_s:.1f}s "
            f"speedup={res.effective_speedup:.2f}x peak_workers={res.peak_concurrency} "
            f"peak_commit={res.peak_commit_used_gb:.2f}GB"
        )
    return 0 if not res.failed_modules else 1


def cmd_shake(args: argparse.Namespace) -> int:
    dag = analyze_project(args.project, heavy_worker_gb=args.heavy_gb)
    targets = args.targets or None
    cfg = SchedulerConfig(
        reserve_commit_gb=args.reserve_gb,
        max_workers=args.max_workers,
        lean_bin=args.lean_bin,
    )
    res = run_lake_shake(
        dag,
        targets,
        apply_fix=args.fix,
        explain=not args.no_explain,
        keep_public=args.keep_public,
        keep_prefix=args.keep_prefix,
        keep_implied=args.keep_implied,
        verify_after_fix=not args.no_verify,
        lean_bin=args.lean_bin,
        scheduler_config=cfg,
    )
    if args.as_json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(f"=== lake shake ({'FIX' if args.fix else 'DRY-RUN'}) ===")
        print(f"Exit code:     {res.returncode}")
        print(f"Files flagged: {len(res.edits)}")
        print(f"Heavy modules: {res.heavy_before} -> {res.heavy_after}")
        if res.backup_dir:
            print(f"Backup dir:    {res.backup_dir}")
        if res.rolled_back_files:
            print(f"Rolled back:   {res.rolled_back_files}")
        for ed in res.edits:
            print(f"  * {ed.file_path}: remove={ed.remove_imports} add={ed.add_imports}")
        if res.raw_output.strip():
            print("\n--- raw lake shake output ---")
            print(res.raw_output.strip()[:2500])
    return res.returncode if args.fix or not res.edits else 0


def cmd_pipeline(args: argparse.Namespace) -> int:
    dag = analyze_project(args.project, heavy_worker_gb=args.heavy_gb)
    targets = args.targets or discover_default_targets(dag.project_root, set(dag.nodes))
    cfg = SchedulerConfig(
        reserve_commit_gb=args.reserve_gb,
        max_workers=args.max_workers,
        lean_bin=args.lean_bin,
    )
    print("Phase 1/2: Commit-charge-aware topological build (generating .oleans for lake shake)...")
    build_res = CommitAwareScheduler(dag, cfg).run(targets)
    if build_res.failed_modules:
        print(f"Build failed on {build_res.failed_modules}; aborting shake phase.")
        return 1

    print("\nPhase 2/2: Running lake shake import minimizer...")
    fresh_dag = analyze_project(args.project, heavy_worker_gb=args.heavy_gb)
    shake_res = run_lake_shake(
        fresh_dag,
        targets,
        apply_fix=args.fix,
        keep_public=args.keep_public,
        verify_after_fix=args.fix,
        lean_bin=args.lean_bin,
        scheduler_config=cfg,
    )
    out = {
        "build": build_res.to_dict(),
        "shake": shake_res.to_dict(),
    }
    if args.as_json:
        print(json.dumps(out, indent=2))
    else:
        print(
            f"\n[PIPELINE COMPLETE] built={build_res.built_modules} "
            f"shake_files={len(shake_res.edits)} "
            f"heavy={shake_res.heavy_before}->{shake_res.heavy_after} "
            f"rolled_back={len(shake_res.rolled_back_files)}"
        )
    return shake_res.returncode if args.fix or not shake_res.edits else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lean-orch",
        description="Windows / Low-RAM Lean 4 import minimizer (lake shake) & commit-aware build orchestrator",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_aud = sub.add_parser("audit", help="Audit Windows commit headroom, DAG, and umbrella-import blast radius")
    _common_args(p_aud)
    p_aud.add_argument("--top", type=int, default=15, help="Number of top umbrella offenders to display")
    p_aud.add_argument("targets", nargs="*", help="Optional target modules")
    p_aud.set_defaults(func=cmd_audit)

    p_bld = sub.add_parser("build", help="Run commit-charge-aware dynamic-concurrency Lake build")
    _common_args(p_bld)
    p_bld.add_argument("--max-heavy", type=int, default=None, help="Explicit cap on concurrent heavy workers")
    p_bld.add_argument("--force", action="store_true", help="Rebuild even if .olean appears fresh")
    p_bld.add_argument("--dry-run", action="store_true", help="Compute schedule without running Lake")
    p_bld.add_argument("--state-file", type=pathlib.Path, default=None, help="Telemetry/checkpoint JSON path")
    p_bld.add_argument("--log-file", type=pathlib.Path, default=None, help="Append timestamped build log")
    p_bld.add_argument("targets", nargs="*", help="Optional target modules")
    p_bld.set_defaults(func=cmd_build)

    p_shk = sub.add_parser("shake", help="Run native `lake shake` with backup/verify/rollback safety")
    _common_args(p_shk)
    p_shk.add_argument("--fix", action="store_true", help="Apply suggested import minimizations in-place")
    p_shk.add_argument("--no-explain", action="store_true", help="Disable --explain output")
    p_shk.add_argument("--keep-public", action="store_true", help="Pass --keep-public to lake shake")
    p_shk.add_argument("--keep-prefix", action="store_true", help="Pass --keep-prefix to lake shake")
    p_shk.add_argument("--keep-implied", action="store_true", help="Pass --keep-implied to lake shake")
    p_shk.add_argument("--no-verify", action="store_true", help="Skip verification rebuild after --fix")
    p_shk.add_argument("targets", nargs="*", help="Optional target modules")
    p_shk.set_defaults(func=cmd_shake)

    p_pip = sub.add_parser("pipeline", help="2-phase workflow: commit-aware build -> lake shake -> verify")
    _common_args(p_pip)
    p_pip.add_argument("--fix", action="store_true", help="Apply lake shake --fix automatically")
    p_pip.add_argument("--keep-public", action="store_true", help="Pass --keep-public to lake shake")
    p_pip.add_argument("targets", nargs="*", help="Optional target modules")
    p_pip.set_defaults(func=cmd_pipeline)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
