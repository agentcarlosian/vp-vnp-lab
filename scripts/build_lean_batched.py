"""
Topological bounded-concurrency Lake builder for Windows (avoids spawning 16
simultaneous `import Mathlib` Lean processes that exceed Windows memory/handle limits).
"""
import ctypes
from ctypes import wintypes
import datetime
import os
import re
import sys
import time
import pathlib
import shutil
import subprocess
from collections import defaultdict, deque

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
VP_VNP = pathlib.Path(os.environ.get("VP_VNP_DIR", str(REPO_ROOT / "formal-math" / "vp-vnp")))
LOG_PATH = pathlib.Path(os.environ.get("VP_VNP_LOG", str(REPO_ROOT / "vp_vnp_build.log")))


def _resolve_lean_bin() -> str:
    exe = "lake.exe" if os.name == "nt" else "lake"
    if os.environ.get("LEAN_BIN"):
        return os.environ["LEAN_BIN"]
    candidates = []
    if os.environ.get("ELAN_HOME"):
        candidates.append(pathlib.Path(os.environ["ELAN_HOME"]))
    candidates.extend([REPO_ROOT / ".elan", pathlib.Path.home() / ".elan"])
    for elan in candidates:
        tcs = elan / "toolchains"
        if tcs.exists():
            pref = tcs / "leanprover--lean4---v4.33.1" / "bin"
            if (pref / exe).exists():
                return str(pref)
            for child in sorted(tcs.iterdir(), reverse=True):
                if (child / "bin" / exe).exists():
                    return str(child / "bin")
    found = shutil.which("lake")
    if found:
        return str(pathlib.Path(found).parent)
    raise FileNotFoundError("Could not locate Lean 4 `lake` binary; set LEAN_BIN or install via elan.")


LEAN_BIN = _resolve_lean_bin()
LAKE_EXE = os.path.join(LEAN_BIN, "lake.exe" if os.name == "nt" else "lake")


class _PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("CommitTotal", ctypes.c_size_t),
        ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t),
        ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t),
        ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t),
        ("PageSize", ctypes.c_size_t),
        ("HandleCount", wintypes.DWORD),
        ("ProcessCount", wintypes.DWORD),
        ("ThreadCount", wintypes.DWORD),
    ]


def avail_commit_gb() -> float:
    try:
        pi = _PERFORMANCE_INFORMATION()
        pi.cb = ctypes.sizeof(pi)
        if ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(pi), pi.cb):
            return (pi.CommitLimit - pi.CommitTotal) * pi.PageSize / (1024 ** 3)
    except Exception:
        pass
    return 999.0


def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def module_name_of(p: pathlib.Path) -> str:
    rel = p.relative_to(VP_VNP).with_suffix("")
    return ".".join(rel.parts)


def collect_dag(targets):
    """Collect all local Lean modules reachable from `targets` and return topological order."""
    local_files = {}
    for top in ("Statement.lean", "Challenge.lean", "Solution.lean", "Paper.lean"):
        fp = VP_VNP / top
        if fp.exists():
            local_files[module_name_of(fp)] = fp
    for folder in ("Ov", "Nc", "NS1", "Paper"):
        d = VP_VNP / folder
        if d.exists():
            for fp in d.rglob("*.lean"):
                local_files[module_name_of(fp)] = fp

    deps = {}
    import_re = re.compile(r"^\s*(?:public\s+)?import\s+([A-Za-z0-9_.]+)", re.M)
    for mod, fp in local_files.items():
        txt = fp.read_text(encoding="utf-8", errors="replace")
        mod_deps = []
        for m in import_re.finditer(txt):
            imp = m.group(1)
            if imp in local_files and imp != mod:
                mod_deps.append(imp)
        deps[mod] = mod_deps

    # Restrict to reachable from targets
    reachable = set()
    stack = list(targets)
    while stack:
        u = stack.pop()
        if u in reachable or u not in local_files:
            continue
        reachable.add(u)
        stack.extend(deps[u])

    # Kahn's topological sort by levels
    indeg = {u: 0 for u in reachable}
    rdeps = defaultdict(list)
    for u in reachable:
        for d in deps[u]:
            if d in reachable:
                indeg[u] += 1
                rdeps[d].append(u)

    levels = []
    q = sorted(u for u in reachable if indeg[u] == 0)
    while q:
        levels.append(q)
        nxt = []
        for u in q:
            for v in rdeps[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    nxt.append(v)
        q = sorted(nxt)

    total = sum(len(lv) for lv in levels)
    assert total == len(reachable), f"Cycle? {total} != {len(reachable)}"
    return levels, local_files


def olean_path(mod: str) -> pathlib.Path:
    return VP_VNP / ".lake" / "build" / "lib" / "lean" / (mod.replace(".", os.sep) + ".olean")


def wait_for_commit_headroom(min_gb: float = 11.5, max_wait_s: int = 300) -> None:
    waited = 0
    while avail_commit_gb() < min_gb and waited < max_wait_s:
        log(f"[WAIT] Available Windows commit charge {avail_commit_gb():.2f} GB < {min_gb:.1f} GB; waiting 5s...")
        time.sleep(5)
        waited += 5


def run_lake_single(mod: str, env: dict, sorry_warnings: list, max_attempts: int = 3) -> tuple[bool, float]:
    t_mod = time.time()
    for attempt in range(1, max_attempts + 1):
        wait_for_commit_headroom(min_gb=11.5)
        r1 = subprocess.run(
            [LAKE_EXE, "build", mod],
            cwd=str(VP_VNP),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        o1 = r1.stdout + "\n" + r1.stderr
        for line in o1.splitlines():
            if "uses 'sorry'" in line:
                sorry_warnings.append(line.strip())
        if r1.returncode == 0:
            return True, time.time() - t_mod
        transient = any(
            tok in o1.lower()
            for tok in ("failed to read file", "not enough memory", "paging file", "1455", "bad_alloc")
        )
        if transient and attempt < max_attempts:
            log(f"[RETRY {attempt}/{max_attempts}] Transient memory error on {mod} (avail={avail_commit_gb():.2f} GB); sleeping 10s...")
            time.sleep(10)
            continue
        log(f"[FAIL] Module {mod} failed (attempt {attempt}, rc={r1.returncode}):\n{o1[-2000:]}")
        return False, time.time() - t_mod
    return False, time.time() - t_mod


def main():
    batch_size = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    targets = sys.argv[2:] if len(sys.argv) > 2 else ["Statement", "Challenge", "Solution", "Paper"]

    levels, _ = collect_dag(targets)
    all_mods = [m for lv in levels for m in lv]
    todo_total = sum(1 for m in all_mods if not olean_path(m).exists())
    log(
        f"Targets: {targets} | Total modules: {len(all_mods)} across {len(levels)} topo levels "
        f"| Remaining: {todo_total} | Batch size: {batch_size} | Avail commit: {avail_commit_gb():.2f} GB"
    )

    env = os.environ.copy()
    env["PATH"] = LEAN_BIN + os.pathsep + env.get("PATH", "")

    t0 = time.time()
    built = 0
    sorry_warnings = []

    for lv_idx, lv in enumerate(levels):
        pending = [m for m in lv if not olean_path(m).exists()]
        if not pending:
            continue
        for i in range(0, len(pending), batch_size):
            batch = pending[i : i + batch_size]
            if len(batch) == 1:
                ok, dt = run_lake_single(batch[0], env, sorry_warnings)
                if not ok:
                    sys.exit(1)
                built += 1
            else:
                wait_for_commit_headroom(min_gb=11.5 * len(batch))
                t_b = time.time()
                res = subprocess.run(
                    [LAKE_EXE, "build"] + batch,
                    cwd=str(VP_VNP),
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                dt = time.time() - t_b
                out = res.stdout + "\n" + res.stderr
                for line in out.splitlines():
                    if "uses 'sorry'" in line:
                        sorry_warnings.append(line.strip())
                if res.returncode != 0:
                    log(f"[RETRY 1-by-1] Batch {batch} failed (rc={res.returncode}), retrying individually...")
                    for m in batch:
                        if olean_path(m).exists():
                            built += 1
                            continue
                        ok, dt = run_lake_single(m, env, sorry_warnings)
                        if not ok:
                            sys.exit(1)
                        built += 1
                else:
                    built += len(batch)
            elapsed = time.time() - t0
            rate = elapsed / max(built, 1)
            eta_min = rate * max(todo_total - built, 0) / 60.0
            log(
                f"  [Level {lv_idx+1}/{len(levels)}] Built {built}/{todo_total} "
                f"({elapsed/60:.1f}m elapsed, ~{eta_min:.0f}m ETA, {dt:.1f}s) "
                f"commit_free={avail_commit_gb():.1f}GB last={batch}"
            )

    # Final verification build of all targets together (instant since all oleans exist!)
    final = subprocess.run(
        [LAKE_EXE, "build"] + targets,
        cwd=str(VP_VNP),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    log("\n=== FINAL lake build ===")
    log(final.stdout + final.stderr)
    if final.returncode != 0:
        sys.exit(final.returncode)

    log(f"\n[SUCCESS] Built all {len(all_mods)} modules in {time.time() - t0:.1f}s!")
    log(f"Sorry warnings observed ({len(sorry_warnings)}):")
    for w in sorted(set(sorry_warnings)):
        log("  " + w)


if __name__ == "__main__":
    main()
