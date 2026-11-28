"""Unit and live Lean 4.33.1 integration tests for lean-build-orchestrator."""

from __future__ import annotations

import os
import pathlib
import shutil
import sys
import time
from typing import Dict, List, Optional

import pytest

# Allow running directly without editable install
PKG_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from lean_orch.dag import analyze_project, parse_imports, strip_lean_comments
from lean_orch.memory import MemorySnapshot, estimate_safe_workers, get_memory_snapshot
from lean_orch.scheduler import CommitAwareScheduler, SchedulerConfig, is_transient_memory_error
from lean_orch.shaker import parse_shake_output, run_lake_shake


def _detect_lean_bin() -> Optional[pathlib.Path]:
    exe = "lake.exe" if os.name == "nt" else "lake"
    if os.environ.get("PCVH_LEAN_BIN"):
        p = pathlib.Path(os.environ["PCVH_LEAN_BIN"])
        if (p / exe).exists():
            return p
    candidates: List[pathlib.Path] = []
    if os.environ.get("ELAN_HOME"):
        candidates.append(pathlib.Path(os.environ["ELAN_HOME"]))
    for anc in [PKG_ROOT, *PKG_ROOT.parents[:4]]:
        if (anc / ".elan").exists():
            candidates.append(anc / ".elan")
    if (pathlib.Path.home() / ".elan").exists():
        candidates.append(pathlib.Path.home() / ".elan")
    for elan in candidates:
        tcs = elan / "toolchains"
        if tcs.exists():
            pref = tcs / "leanprover--lean4---v4.33.1" / "bin"
            if (pref / exe).exists():
                return pref
            for child in sorted(tcs.iterdir(), reverse=True):
                if (child / "bin" / exe).exists():
                    return child / "bin"
    w = shutil.which("lake")
    return pathlib.Path(w).parent if w else None


LOCAL_LEAN_BIN = _detect_lean_bin()


def test_memory_snapshot_live():
    snap = get_memory_snapshot()
    assert snap.physical_total_gb > 0
    assert snap.commit_limit_gb > 0 and snap.commit_total_gb >= 0
    assert snap.scheduler_headroom_gb >= 0
    if sys.platform == "win32":
        assert snap.commit_limit_gb >= snap.commit_total_gb
        assert snap.source == "win32:GetPerformanceInfo"


@pytest.mark.parametrize(("policy", "headroom"), [("0", 5.0), ("1", 5.0), ("2", 0.0)])
def test_linux_overcommit_headroom_preserves_raw_counters(monkeypatch, policy, headroom):
    import builtins
    import io
    from lean_orch import memory

    meminfo = "MemTotal: 8388608 kB\nMemAvailable: 4194304 kB\nSwapFree: 1048576 kB\nCommitLimit: 4194304 kB\nCommitted_AS: 6291456 kB\n"
    real_open = builtins.open
    real_exists = memory.os.path.exists
    real_read_text = pathlib.Path.read_text

    monkeypatch.setattr(memory.sys, "platform", "linux")
    monkeypatch.setattr(memory.os.path, "exists", lambda path: path == "/proc/meminfo" or real_exists(path))
    monkeypatch.setattr(builtins, "open", lambda path, *a, **kw: io.StringIO(meminfo) if path == "/proc/meminfo" else real_open(path, *a, **kw))
    monkeypatch.setattr(pathlib.Path, "read_text", lambda path, *a, **kw: policy if path.as_posix() == "/proc/sys/vm/overcommit_memory" else real_read_text(path, *a, **kw))

    snap = get_memory_snapshot()
    assert snap.commit_total_gb == 6.0
    assert snap.commit_limit_gb == 4.0
    assert snap.commit_avail_gb == 0
    assert snap.scheduler_headroom_gb == headroom


def test_estimate_safe_workers():
    assert estimate_safe_workers(avail_commit_gb=19.0, per_worker_gb=10.5, reserve_gb=3.0) == 1
    assert estimate_safe_workers(avail_commit_gb=26.0, per_worker_gb=10.5, reserve_gb=3.0) == 2
    assert estimate_safe_workers(avail_commit_gb=20.0, per_worker_gb=0.5, reserve_gb=3.0, max_cap=8) == 8


def test_parse_imports_strips_nested_comments_and_strings():
    src = """
/- outer comment
   /- nested comment
      import Mathlib
   -/
   import Fake.Nested
-/
-- import Mathlib
import Foo.Bar
public import Baz.Qux
import all Std.Data.HashMap

def hint : String := "import Mathlib"
theorem ok : True := trivial
"""
    assert parse_imports(src) == ["Foo.Bar", "Baz.Qux", "Std.Data.HashMap"]
    assert "Fake.Nested" not in strip_lean_comments(src)


def test_dag_umbrella_blast_radius(tmp_path: pathlib.Path):
    # Diamond graph:
    #   BaseA (import Mathlib) -> Mid1 -> Top
    #   BaseB (import Mathlib) -> Mid2 -> Top
    #   LeafLight (no Mathlib) -> Top
    (tmp_path / "lakefile.toml").write_text('name = "demo"\n', encoding="utf-8")
    (tmp_path / "BaseA.lean").write_text("import Mathlib\ndef a := 1\n", encoding="utf-8")
    (tmp_path / "BaseB.lean").write_text("import Mathlib\ndef b := 2\n", encoding="utf-8")
    (tmp_path / "Mid1.lean").write_text("import BaseA\ndef m1 := a\n", encoding="utf-8")
    (tmp_path / "Mid2.lean").write_text("import BaseB\ndef m2 := b\n", encoding="utf-8")
    (tmp_path / "LeafLight.lean").write_text("def l := 3\n", encoding="utf-8")
    (tmp_path / "Top.lean").write_text(
        "import Mid1\nimport Mid2\nimport LeafLight\ndef t := m1 + m2 + l\n",
        encoding="utf-8",
    )

    dag = analyze_project(tmp_path, heavy_worker_gb=10.0)
    assert dag.nodes["LeafLight"].weight_class == "light"
    assert dag.nodes["Mid1"].weight_class == "heavy"
    assert dag.nodes["Top"].weight_class == "heavy"

    offenders = {r.module: r for r in dag.umbrella_blast_radius()}
    assert set(offenders.keys()) == {"BaseA", "BaseB"}
    # BaseA reaches {BaseA, Mid1, Top} (3), exclusively poisons {BaseA, Mid1} (2) because Top also gets Mathlib via BaseB
    assert offenders["BaseA"].downstream_poisoned_count == 3
    assert offenders["BaseA"].exclusively_poisoned_count == 2


class _MockProc:
    def __init__(self, rc: int, output: str, delay_s: float = 0.05) -> None:
        self._rc = rc
        self._out = output
        self._done_at = time.time() + delay_s

    def poll(self):
        return self._rc if time.time() >= self._done_at else None

    def communicate(self, timeout=None):
        return self._out, ""


def test_scheduler_serializes_heavy_and_retries_transient_oom(tmp_path: pathlib.Path):
    (tmp_path / "H1.lean").write_text("import Mathlib\ndef h1 := 1\n", encoding="utf-8")
    (tmp_path / "H2.lean").write_text("import Mathlib\ndef h2 := 2\n", encoding="utf-8")
    (tmp_path / "L1.lean").write_text("def l1 := 1\n", encoding="utf-8")
    (tmp_path / "Top.lean").write_text("import H1\nimport H2\nimport L1\ndef t := 0\n", encoding="utf-8")

    dag = analyze_project(tmp_path, heavy_worker_gb=10.0, light_worker_gb=0.4)
    # 18 GB available commit -> at most 1 heavy worker at a time, plus light workers!
    snap = MemorySnapshot(
        platform="win32",
        physical_total_gb=32.0,
        physical_avail_gb=16.0,
        commit_total_gb=22.0,
        commit_limit_gb=40.0,
        commit_peak_gb=22.0,
        page_size_bytes=4096,
        process_count=100,
        source="mock",
    )

    spawn_counts: Dict[str, int] = {}
    concurrent_heavy_max = 0
    active_heavy: List[str] = []

    def mock_spawner(mod: str, cwd: pathlib.Path, env: Dict[str, str]):
        nonlocal concurrent_heavy_max
        spawn_counts[mod] = spawn_counts.get(mod, 0) + 1
        if mod in ("H1", "H2"):
            active_heavy.append(mod)
            concurrent_heavy_max = max(concurrent_heavy_max, len(active_heavy))

        class _TrackedProc(_MockProc):
            def poll(self_inner):
                rc = super().poll()
                if rc is not None and mod in active_heavy:
                    active_heavy.remove(mod)
                return rc

        # First attempt of H1 hits a transient Windows .olean.private error!
        if mod == "H1" and spawn_counts[mod] == 1:
            return _TrackedProc(1, "error: failed to read file 'Mathlib/Foo.olean.private'", delay_s=0.03)
        return _TrackedProc(0, "Build completed successfully", delay_s=0.04)

    cfg = SchedulerConfig(
        reserve_commit_gb=3.0,
        max_workers=4,
        poll_interval_s=0.01,
        retry_backoff_s=0.05,
        ramp_up_window_s=0.5,
        state_file=tmp_path / "state.json",
    )
    sched = CommitAwareScheduler(dag, cfg, memory_probe=lambda: snap, spawner=mock_spawner)
    res = sched.run(["Top"])

    assert res.failed_modules == []
    assert res.built_modules == 4
    assert spawn_counts["H1"] == 2  # retried once after transient OOM
    assert concurrent_heavy_max == 1  # never ran H1 and H2 concurrently!
    assert (tmp_path / "state.json").exists()
    assert is_transient_memory_error("error: failed to read file 'X.olean.private'")


def test_parse_shake_output_formats():
    sample = r"""
Demo/Top.lean:
  remove `import Demo.Unused`
  replace `import Mathlib` with `import Mathlib.Data.Nat.Basic`
C:\Users\Dev\Mini\App.lean:
  remove #[public import Mini.Unused]
  note: `public import Mini.Used` required
    because `check_magic` refers to `magicNumber`
"""
    edits = parse_shake_output(sample)
    assert len(edits) == 2
    by_fp = {e.file_path: e for e in edits}
    assert "Demo.Unused" in by_fp["Demo/Top.lean"].remove_imports
    assert "Mathlib" in by_fp["Demo/Top.lean"].remove_imports
    assert "Mathlib.Data.Nat.Basic" in by_fp["Demo/Top.lean"].add_imports
    assert by_fp[r"C:\Users\Dev\Mini\App.lean"].remove_imports == ["Mini.Unused"]


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4 toolchain not present")
def test_live_lean4_module_native_lake_shake_e2e(tmp_path: pathlib.Path):
    """Real E2E build + native `lake shake --fix` + verify on a Lean 4.33.1 `module` project."""
    proj = tmp_path / "mini_mod"
    (proj / "Mini").mkdir(parents=True)
    (proj / "lean-toolchain").write_text("leanprover/lean4:v4.33.1\n", encoding="utf-8")
    (proj / "lakefile.toml").write_text(
        'name = "mini_mod"\ndefaultTargets = ["Mini"]\n\n[[lean_lib]]\nname = "Mini"\n',
        encoding="utf-8",
    )
    (proj / "Mini" / "Used.lean").write_text("module\n@[expose] public def magicNumber : Nat := 42\n", encoding="utf-8")
    (proj / "Mini" / "Unused.lean").write_text("module\n@[expose] public def deadWeight : Nat := 999\n", encoding="utf-8")
    (proj / "Mini" / "App.lean").write_text(
        "module\npublic import Mini.Used\npublic import Mini.Unused\n\npublic theorem check_magic : magicNumber = 42 := rfl\n",
        encoding="utf-8",
    )
    (proj / "Mini.lean").write_text("module\npublic import Mini.App\n", encoding="utf-8")

    dag = analyze_project(proj)
    cfg = SchedulerConfig(lean_bin=LOCAL_LEAN_BIN, max_workers=2, poll_interval_s=0.1)
    build_res = CommitAwareScheduler(dag, cfg).run(["Mini"])
    assert build_res.failed_modules == []
    assert build_res.built_modules == 4

    fresh_dag = analyze_project(proj)
    shake_res = run_lake_shake(
        fresh_dag,
        ["Mini"],
        apply_fix=True,
        verify_after_fix=True,
        lean_bin=LOCAL_LEAN_BIN,
        scheduler_config=cfg,
    )
    app_src = (proj / "Mini" / "App.lean").read_text(encoding="utf-8")
    assert shake_res.backend == "native-lake-shake"
    assert shake_res.backup_dir is not None and shake_res.backup_dir.exists()
    assert shake_res.rolled_back_files == []
    assert "Mini.Unused" not in app_src
    assert "Mini.Used" in app_src


@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean 4 toolchain not present")
def test_live_lean4_non_module_fallback_shake_e2e(tmp_path: pathlib.Path):
    """Real E2E build + automatic `.olean` env fallback minimizer on a traditional non-`module` Lean 4 project."""
    proj = tmp_path / "mini_legacy"
    (proj / "Mini").mkdir(parents=True)
    (proj / "lean-toolchain").write_text("leanprover/lean4:v4.33.1\n", encoding="utf-8")
    (proj / "lakefile.toml").write_text(
        'name = "mini_legacy"\ndefaultTargets = ["Mini"]\n\n[[lean_lib]]\nname = "Mini"\n',
        encoding="utf-8",
    )
    (proj / "Mini" / "Used.lean").write_text("def magicNumber : Nat := 42\n", encoding="utf-8")
    (proj / "Mini" / "Unused.lean").write_text("def deadWeight : Nat := 999\n", encoding="utf-8")
    (proj / "Mini" / "App.lean").write_text(
        "import Mini.Used\nimport Mini.Unused\n\ntheorem check_magic : magicNumber = 42 := rfl\n",
        encoding="utf-8",
    )
    (proj / "Mini.lean").write_text("import Mini.App\n", encoding="utf-8")

    dag = analyze_project(proj)
    cfg = SchedulerConfig(lean_bin=LOCAL_LEAN_BIN, max_workers=2, poll_interval_s=0.1)
    build_res = CommitAwareScheduler(dag, cfg).run(["Mini"])
    assert build_res.failed_modules == []
    assert build_res.built_modules == 4

    fresh_dag = analyze_project(proj)
    shake_res = run_lake_shake(
        fresh_dag,
        ["Mini"],
        apply_fix=True,
        verify_after_fix=True,
        lean_bin=LOCAL_LEAN_BIN,
        scheduler_config=cfg,
    )
    app_src = (proj / "Mini" / "App.lean").read_text(encoding="utf-8")
    assert shake_res.backend == "lean-env-fallback"
    assert shake_res.backup_dir is not None and shake_res.backup_dir.exists()
    assert shake_res.rolled_back_files == []
    assert "Mini.Unused" not in app_src
    assert "Mini.Used" in app_src

@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean toolchain missing")
def test_partial_dependency_rebuild_invalidates_client(tmp_path):
    import subprocess

    (tmp_path / "Mini").mkdir()
    (tmp_path / "lean-toolchain").write_text("leanprover/lean4:v4.33.1\n")
    (tmp_path / "lakefile.toml").write_text('name = "mini"\n[[lean_lib]]\nname = "Mini"\n')
    base = tmp_path / "Mini" / "Base.lean"
    base.write_text("def baseValue : Nat := 1\n")
    (base.parent / "Client.lean").write_text("import Mini.Base\ndef clientValue : Nat := baseValue\n")
    lake = LOCAL_LEAN_BIN / ("lake.exe" if os.name == "nt" else "lake")
    subprocess.run([str(lake), "build", "Mini.Client"], cwd=tmp_path, check=True)
    cached = analyze_project(tmp_path)
    assert cached.nodes["Mini.Client"].olean_fresh
    base.write_text('def baseValue : String := "changed"\n')
    subprocess.run([str(lake), "build", "Mini.Base"], cwd=tmp_path, check=True)
    dag = analyze_project(tmp_path)
    assert dag.nodes["Mini.Base"].olean_fresh and not dag.nodes["Mini.Client"].olean_fresh
    result = CommitAwareScheduler(dag, SchedulerConfig(lean_bin=LOCAL_LEAN_BIN)).run(["Mini.Client"])
    assert "Mini.Client" in result.failed_modules
    # A caller can retain a DAG across this dependency edit. Lake checks the
    # requested root even when that original snapshot still looks fresh.
    assert "Mini.Client" in CommitAwareScheduler(cached, SchedulerConfig(lean_bin=LOCAL_LEAN_BIN)).run(["Mini.Client"]).failed_modules

@pytest.mark.skipif(LOCAL_LEAN_BIN is None, reason="Lean toolchain missing")
def test_shake_restores_the_edited_dependency_on_consumer_failure(tmp_path):
    import subprocess

    mini = tmp_path / "Mini"
    mini.mkdir()
    (tmp_path / "lean-toolchain").write_text("leanprover/lean4:v4.33.1\n")
    (tmp_path / "lakefile.toml").write_text('name = "mini"\n[[lean_lib]]\nname = "Mini"\n')
    (mini / "Base.lean").write_text("def baseValue : Nat := 1\n")
    middle = mini / "Middle.lean"
    middle.write_text("import Mini.Base\ndef marker : Nat := 2\n")
    original = middle.read_bytes()
    (mini / "Client.lean").write_text("import Mini.Middle\ndef client : Nat := marker + baseValue\n")
    lake = LOCAL_LEAN_BIN / ("lake.exe" if os.name == "nt" else "lake")
    command = [str(lake), "build", "Mini.Client"]
    subprocess.run(command, cwd=tmp_path, check=True)
    result = run_lake_shake(analyze_project(tmp_path), ["Mini.Client"], apply_fix=True, lean_bin=LOCAL_LEAN_BIN)
    assert result.returncode != 0
    assert "Mini.Middle" in result.rolled_back_files
    assert middle.read_bytes() == original
    subprocess.run(command, cwd=tmp_path, check=True)
