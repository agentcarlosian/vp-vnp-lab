"""Commit-charge-aware dynamic-concurrency topological scheduler for Lake builds on Windows/Low-RAM."""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import json
import os
import pathlib
import subprocess
import tempfile
import time
from typing import Callable, Dict, IO, List, Optional, Sequence, Set, Tuple

from .dag import ProjectDAG, resolve_lake_executable
from .memory import MemorySnapshot, get_memory_snapshot

TRANSIENT_OOM_MARKERS = (
    "failed to read file",
    "not enough memory",
    "paging file",
    "1455",
    "bad_alloc",
    "out of memory",
    "cannot allocate memory",
    "std::bad_alloc",
    "insufficient system resources",
)


@dataclass
class SchedulerConfig:
    reserve_commit_gb: float = 3.0
    max_workers: int = 8
    max_heavy_workers: Optional[int] = None  # auto-computed from commit limit if None
    ramp_up_window_s: float = 15.0
    poll_interval_s: float = 0.25
    max_retries: int = 3
    retry_backoff_s: float = 8.0
    force_rebuild: bool = False
    dry_run: bool = False
    lean_bin: Optional[pathlib.Path] = None
    state_file: Optional[pathlib.Path] = None
    log_file: Optional[pathlib.Path] = None


@dataclass
class ModuleBuildRecord:
    module: str
    weight_class: str
    status: str  # "built" | "cached" | "failed" | "skipped"
    duration_s: float
    attempts: int
    estimated_commit_gb: float
    observed_peak_commit_delta_gb: float
    sorry_warnings: List[str] = field(default_factory=list)
    error_tail: str = ""


@dataclass
class BuildSummary:
    total_target_modules: int
    cached_modules: int
    built_modules: int
    failed_modules: List[str]
    wall_time_s: float
    sum_module_time_s: float
    peak_concurrency: int
    peak_commit_used_gb: float
    sorry_warnings: List[str]
    records: Dict[str, ModuleBuildRecord]

    @property
    def effective_speedup(self) -> float:
        if self.wall_time_s <= 0:
            return 1.0
        return self.sum_module_time_s / self.wall_time_s

    def to_dict(self) -> Dict[str, object]:
        return {
            "total_target_modules": self.total_target_modules,
            "cached_modules": self.cached_modules,
            "built_modules": self.built_modules,
            "failed_modules": list(self.failed_modules),
            "wall_time_s": round(self.wall_time_s, 2),
            "sum_module_time_s": round(self.sum_module_time_s, 2),
            "effective_speedup": round(self.effective_speedup, 2),
            "peak_concurrency": self.peak_concurrency,
            "peak_commit_used_gb": round(self.peak_commit_used_gb, 2),
            "sorry_warnings": sorted(set(self.sorry_warnings)),
        }


@dataclass
class _RunningWorker:
    module: str
    weight_class: str
    estimated_commit_gb: float
    proc: object  # subprocess.Popen or mock
    started_at: float
    baseline_commit_gb: float
    attempt: int
    peak_commit_delta_gb: float = 0.0
    out_file: Optional[IO[str]] = None


def is_transient_memory_error(output: str) -> bool:
    low = output.lower()
    return any(marker in low for marker in TRANSIENT_OOM_MARKERS)


class CommitAwareScheduler:
    """Schedules Lean 4 module builds dynamically based on live Windows commit-charge headroom."""

    def __init__(
        self,
        dag: ProjectDAG,
        config: Optional[SchedulerConfig] = None,
        memory_probe: Callable[[], MemorySnapshot] = get_memory_snapshot,
        spawner: Optional[Callable[[str, pathlib.Path, Dict[str, str]], object]] = None,
    ) -> None:
        self.dag = dag
        self.config = config or SchedulerConfig()
        self.memory_probe = memory_probe
        self._custom_spawner = spawner
        self._calibrated_weights: Dict[str, float] = {}
        self._load_state_calibration()

    def _state_path(self) -> pathlib.Path:
        if self.config.state_file is not None:
            return self.config.state_file
        return self.dag.project_root / ".lean-orch-state.json"

    def _load_state_calibration(self) -> None:
        sp = self._state_path()
        if not sp.exists():
            return
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
            for mod, rec in data.get("modules", {}).items():
                obs = rec.get("observed_peak_commit_delta_gb", 0.0)
                if isinstance(obs, (int, float)) and obs > 0.2:
                    self._calibrated_weights[mod] = float(obs) * 1.15
        except Exception:
            pass

    def _save_state(self, records: Dict[str, ModuleBuildRecord]) -> None:
        if self.config.dry_run:
            return
        sp = self._state_path()
        payload = {
            "updated_at": datetime.datetime.now().isoformat(),
            "project_root": str(self.dag.project_root),
            "modules": {
                m: {
                    "weight_class": r.weight_class,
                    "status": r.status,
                    "duration_s": round(r.duration_s, 2),
                    "attempts": r.attempts,
                    "estimated_commit_gb": round(r.estimated_commit_gb, 2),
                    "observed_peak_commit_delta_gb": round(r.observed_peak_commit_delta_gb, 2),
                }
                for m, r in records.items()
            },
        }
        try:
            sp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _log(self, msg: str) -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        if self.config.log_file is not None:
            self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
            with self.config.log_file.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def module_weight_gb(self, mod: str) -> float:
        base = self.dag.nodes[mod].estimated_commit_gb
        if mod in self._calibrated_weights:
            return max(0.35, min(base * 1.3, self._calibrated_weights[mod]))
        return base

    def compute_effective_heavy_cap(self, snap: MemorySnapshot) -> int:
        if self.config.max_heavy_workers is not None:
            return max(1, self.config.max_heavy_workers)
        usable = max(0.0, snap.scheduler_headroom_gb - self.config.reserve_commit_gb)
        cap = int(usable // max(0.5, self.dag.heavy_worker_gb))
        return max(1, min(self.config.max_workers, cap))

    def can_admit(
        self,
        mod: str,
        snap: MemorySnapshot,
        running: Sequence[_RunningWorker],
        now: float,
        dynamic_worker_cap: int,
        heavy_cap: int,
    ) -> bool:
        if len(running) >= dynamic_worker_cap:
            return False

        node = self.dag.nodes[mod]
        w_gb = self.module_weight_gb(mod)

        running_heavy = sum(1 for r in running if r.weight_class == "heavy")
        if node.weight_class == "heavy" and running_heavy >= heavy_cap:
            return False

        # Conservative ramp-up reservation: recently spawned Lean workers haven't
        # finished memory-mapping Mathlib yet, so subtract their unmaterialized commit.
        unmaterialized_gb = 0.0
        for r in running:
            age = now - r.started_at
            if age < self.config.ramp_up_window_s:
                unmaterialized_gb += max(0.0, r.estimated_commit_gb - r.peak_commit_delta_gb)

        effective_avail = snap.scheduler_headroom_gb - unmaterialized_gb
        # Always allow at least 1 worker if nothing is running and commit isn't critically exhausted
        if not running:
            return effective_avail >= min(w_gb * 0.65, max(0.5, snap.commit_limit_gb * 0.1))
        return (effective_avail - w_gb) >= self.config.reserve_commit_gb

    def _pending_modules(self, modules: Sequence[str]) -> Set[str]:
        # Timestamps help schedule work, but cannot certify every Lake input
        # (toolchain, build options, external imports, or an equal-time edit).
        # Ask Lake to validate the roots even when all local artifacts look fresh.
        dependencies = {d for m in modules for d in self.dag.nodes[m].local_deps}
        return {m for m in modules if self.config.force_rebuild or
                not self.dag.nodes[m].olean_fresh or m not in dependencies}

    def simulate_plan(self, targets: Optional[Sequence[str]] = None) -> Dict[str, object]:
        """Estimate build schedule, concurrency tiers, and speedup without executing Lake."""
        sub = self.dag.reachable_subgraph(targets)
        snap = self.memory_probe()
        heavy_cap = self.compute_effective_heavy_cap(snap)
        usable = max(0.5, snap.scheduler_headroom_gb - self.config.reserve_commit_gb)
        light_cap = max(1, min(self.config.max_workers, int(usable // max(0.2, self.dag.light_worker_gb))))
        medium_cap = max(1, min(self.config.max_workers, int(usable // max(0.5, self.dag.medium_worker_gb))))

        pending = self._pending_modules(sub)
        heavy_pending = [m for m in pending if self.dag.nodes[m].weight_class == "heavy"]
        medium_pending = [m for m in pending if self.dag.nodes[m].weight_class == "medium"]
        light_pending = [m for m in pending if self.dag.nodes[m].weight_class == "light"]

        # Rough wall-time model: heavy ~65s, medium ~15s, light ~4s
        seq_est_s = len(heavy_pending) * 65.0 + len(medium_pending) * 15.0 + len(light_pending) * 4.0
        sched_est_s = (
            len(heavy_pending) * 65.0 / heavy_cap
            + len(medium_pending) * 15.0 / medium_cap
            + len(light_pending) * 4.0 / light_cap
        )
        # Counterfactual if all heavy modules are shaken down to medium/light
        post_shake_est_s = (len(heavy_pending) + len(medium_pending)) * 12.0 / medium_cap + len(light_pending) * 4.0 / light_cap

        return {
            "memory": snap.to_dict(),
            "targets_total": len(sub),
            "pending_total": len(pending),
            "pending_by_class": {
                "heavy": len(heavy_pending),
                "medium": len(medium_pending),
                "light": len(light_pending),
            },
            "safe_concurrency": {
                "heavy_workers": heavy_cap,
                "medium_workers": medium_cap,
                "light_workers": light_cap,
            },
            "estimated_wall_minutes": {
                "naive_sequential": round(seq_est_s / 60.0, 1),
                "commit_aware_current": round(sched_est_s / 60.0, 1),
                "post_lake_shake_projected": round(post_shake_est_s / 60.0, 1),
            },
            "projected_shake_speedup_x": round(sched_est_s / max(1.0, post_shake_est_s), 2),
        }

    def run(self, targets: Optional[Sequence[str]] = None) -> BuildSummary:
        """Execute memory-aware topological Lake build for all pending reachable modules."""
        sub = self.dag.reachable_subgraph(targets)
        sub_set = set(sub)
        pending_modules = self._pending_modules(sub)
        t0 = time.time()

        records: Dict[str, ModuleBuildRecord] = {}
        done: Set[str] = set()
        failed: Set[str] = set()
        sorry_warnings: List[str] = []

        for m in sub:
            node = self.dag.nodes[m]
            if m not in pending_modules:
                done.add(m)
                records[m] = ModuleBuildRecord(
                    module=m,
                    weight_class=node.weight_class,
                    status="cached",
                    duration_s=0.0,
                    attempts=0,
                    estimated_commit_gb=self.module_weight_gb(m),
                    observed_peak_commit_delta_gb=0.0,
                )

        pending_total = len(sub) - len(done)
        snap0 = self.memory_probe()
        heavy_cap = self.compute_effective_heavy_cap(snap0)
        self._log(
            f"Orchestrator starting | modules={len(sub)} cached={len(done)} pending={pending_total} "
            f"| max_workers={self.config.max_workers} heavy_cap={heavy_cap} "
            f"reserve={self.config.reserve_commit_gb:.1f}GB | {snap0.format_human()}"
        )

        if self.config.dry_run or pending_total == 0:
            return BuildSummary(
                total_target_modules=len(sub),
                cached_modules=len(done),
                built_modules=0,
                failed_modules=[],
                wall_time_s=time.time() - t0,
                sum_module_time_s=0.0,
                peak_concurrency=0,
                peak_commit_used_gb=snap0.commit_total_gb,
                sorry_warnings=[],
                records=records,
            )

        lake_exe: Optional[pathlib.Path] = None
        env = os.environ.copy()
        if self._custom_spawner is None:
            lake_exe, lean_bin_dir = resolve_lake_executable(
                self.dag.project_root, self.config.lean_bin
            )
            if lean_bin_dir is not None:
                env["PATH"] = str(lean_bin_dir) + os.pathsep + env.get("PATH", "")

        def default_spawn(mod: str, cwd: pathlib.Path, proc_env: Dict[str, str]) -> Tuple[subprocess.Popen, IO[str]]:
            assert lake_exe is not None
            # Use a temporary file instead of subprocess.PIPE to prevent Windows 4KB pipe-buffer deadlocks
            # when polling `proc.poll()` before reading output.
            out_fh = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
            proc = subprocess.Popen(
                [str(lake_exe), "build", mod],
                cwd=str(cwd),
                env=proc_env,
                stdout=out_fh,
                stderr=subprocess.STDOUT,
            )
            return proc, out_fh

        spawn_fn = self._custom_spawner or default_spawn

        # Track remaining indegree among unbuilt subgraph
        rem_deps: Dict[str, Set[str]] = {
            m: {d for d in self.dag.nodes[m].local_deps if d in sub_set and d not in done}
            for m in sub
            if m not in done
        }
        ready: List[str] = [m for m, deps in rem_deps.items() if not deps]
        attempts: Dict[str, int] = {m: 0 for m in rem_deps}
        backoff_until: Dict[str, float] = {}
        running: List[_RunningWorker] = []

        dynamic_worker_cap = self.config.max_workers
        peak_concurrency = 0
        peak_commit_used = snap0.commit_total_gb
        sum_module_time = 0.0
        built_count = 0

        def priority_key(mod: str) -> Tuple[int, int, str]:
            # Prefer critical-path modules first; break ties by lighter modules to pack alongside heavy ones
            node = self.dag.nodes[mod]
            class_rank = {"light": 0, "medium": 1, "heavy": 2}.get(node.weight_class, 2)
            return (-node.critical_path_depth, class_rank, mod)

        while ready or running or backoff_until:
            now = time.time()
            snap = self.memory_probe()
            peak_commit_used = max(peak_commit_used, snap.commit_total_gb)

            # Re-admit backed-off modules whose cooldown expired
            for mod in list(backoff_until.keys()):
                if now >= backoff_until[mod]:
                    del backoff_until[mod]
                    ready.append(mod)

            # Update observed commit delta for active workers & reap finished ones
            still_running: List[_RunningWorker] = []
            for w in running:
                delta = max(0.0, snap.commit_total_gb - w.baseline_commit_gb)
                w.peak_commit_delta_gb = max(w.peak_commit_delta_gb, delta)

                rc = w.proc.poll()
                if rc is None:
                    still_running.append(w)
                    continue

                out = ""
                if w.out_file is not None:
                    try:
                        w.out_file.flush()
                        w.out_file.seek(0)
                        out = w.out_file.read()
                    except Exception:
                        pass
                    finally:
                        try:
                            w.out_file.close()
                        except Exception:
                            pass
                else:
                    try:
                        stdout_data, _ = w.proc.communicate(timeout=5)
                        out = stdout_data or ""
                    except Exception:
                        pass

                dt = time.time() - w.started_at
                mod_sorries = [
                    ln.strip() for ln in out.splitlines() if "uses 'sorry'" in ln
                ]
                sorry_warnings.extend(mod_sorries)

                if rc == 0:
                    done.add(w.module)
                    built_count += 1
                    sum_module_time += dt
                    records[w.module] = ModuleBuildRecord(
                        module=w.module,
                        weight_class=w.weight_class,
                        status="built",
                        duration_s=dt,
                        attempts=w.attempt,
                        estimated_commit_gb=w.estimated_commit_gb,
                        observed_peak_commit_delta_gb=w.peak_commit_delta_gb,
                        sorry_warnings=mod_sorries,
                    )
                    if w.peak_commit_delta_gb > 0.25:
                        self._calibrated_weights[w.module] = w.peak_commit_delta_gb * 1.15
                    self._save_state(records)

                    # Unlock dependents
                    for child in self.dag.rdeps.get(w.module, []):
                        if child in rem_deps:
                            rem_deps[child].discard(w.module)
                            if not rem_deps[child]:
                                ready.append(child)

                    elapsed = time.time() - t0
                    self._log(
                        f"  [OK {built_count}/{pending_total}] {w.module} ({w.weight_class}) "
                        f"in {dt:.1f}s (peak Δcommit={w.peak_commit_delta_gb:.2f}GB, "
                        f"free={snap.scheduler_headroom_gb:.1f}GB, elapsed={elapsed:.0f}s)"
                    )
                else:
                    if is_transient_memory_error(out) and w.attempt < self.config.max_retries:
                        # Back off & tighten concurrency cap to avoid repeated commit thrash
                        dynamic_worker_cap = max(1, min(dynamic_worker_cap - 1, max(1, len(running) - 1)))
                        heavy_cap = 1
                        wait_s = self.config.retry_backoff_s * w.attempt
                        backoff_until[w.module] = time.time() + wait_s
                        self._log(
                            f"  [MEM-RETRY {w.attempt}/{self.config.max_retries}] {w.module} "
                            f"hit Windows commit pressure; capping workers={dynamic_worker_cap}, "
                            f"retrying in {wait_s:.0f}s"
                        )
                    else:
                        failed.add(w.module)
                        records[w.module] = ModuleBuildRecord(
                            module=w.module,
                            weight_class=w.weight_class,
                            status="failed",
                            duration_s=dt,
                            attempts=w.attempt,
                            estimated_commit_gb=w.estimated_commit_gb,
                            observed_peak_commit_delta_gb=w.peak_commit_delta_gb,
                            sorry_warnings=mod_sorries,
                            error_tail=out[-1500:],
                        )
                        self._save_state(records)
                        self._log(f"  [FAIL] {w.module} (rc={rc}, attempt={w.attempt}): {out[-400:].strip()}")
            running = still_running

            # Schedule new workers if commit budget permits
            if ready:
                ready.sort(key=priority_key)
                deferred: List[str] = []
                for mod in ready:
                    if self.can_admit(mod, snap, running, now, dynamic_worker_cap, heavy_cap):
                        attempts[mod] = attempts.get(mod, 0) + 1
                        spawned = spawn_fn(mod, self.dag.project_root, env)
                        if isinstance(spawned, tuple):
                            proc, out_fh = spawned
                        else:
                            proc, out_fh = spawned, None
                        w = _RunningWorker(
                            module=mod,
                            weight_class=self.dag.nodes[mod].weight_class,
                            estimated_commit_gb=self.module_weight_gb(mod),
                            proc=proc,
                            started_at=time.time(),
                            baseline_commit_gb=snap.commit_total_gb,
                            attempt=attempts[mod],
                            out_file=out_fh,
                        )
                        running.append(w)
                        peak_concurrency = max(peak_concurrency, len(running))
                    else:
                        deferred.append(mod)
                ready = deferred

            if running or backoff_until:
                time.sleep(self.config.poll_interval_s)
            elif ready:
                # Waiting for commit headroom to recover from external processes
                time.sleep(max(0.5, self.config.poll_interval_s * 4))

        return BuildSummary(
            total_target_modules=len(sub),
            cached_modules=len(sub) - pending_total,
            built_modules=built_count,
            failed_modules=sorted(failed),
            wall_time_s=time.time() - t0,
            sum_module_time_s=sum_module_time,
            peak_concurrency=peak_concurrency,
            peak_commit_used_gb=peak_commit_used,
            sorry_warnings=sorted(set(sorry_warnings)),
            records=records,
        )
