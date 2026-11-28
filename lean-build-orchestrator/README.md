# `lean-build-orchestrator` (`lean-orch`)

Windows / Low-RAM Lean 4 import minimizer (`lake shake`) and commit-charge-aware Lake build orchestrator.

## Why This Exists
On Windows, every Lean 4 worker (`lean.exe`) that transitively imports an umbrella module like `import Mathlib` memory-maps thousands of `.olean` and `.olean.private` files, consuming **~9–11 GB of Windows pagefile commit charge** per process. Standard `lake build` spawns `N` parallel workers (up to CPU core count), crashing immediately with:

```text
error: failed to read file '.../.lake/build/lib/lean/Mathlib/...olean.private'
```

Meanwhile, Lean 4's built-in `lake shake` import minimizer requires `.olean` files to exist first — creating a chicken-and-egg deadlock on Windows laptops.

`lean-orch` breaks the deadlock with a 2-phase workflow:
1. **Audit & Blast-Radius Analysis (`audit`)**: Reads Win32 `GetPerformanceInfo` commit charge (`CommitLimit - CommitTotal`), measures `.lake/packages` `.olean*` footprint, parses the comment-aware Lean import DAG, and ranks direct `import Mathlib` offenders by downstream poison and exclusive unlock impact.
2. **Commit-Aware Topological Build (`build`)**: Schedules modules dynamically in critical-path order while gating spawns against live Windows commit headroom + ramp-up reservations (serializing `heavy` modules while packing `light` modules in parallel, with automatic OOM backoff/retry and `.lean-orch-state.json` calibration).
3. **Safe `lake shake` Minimization (`shake` / `pipeline`)**: Runs native `lake shake`, backs up modified `.lean` files, applies `--fix`, rebuilds to verify, and automatically rolls back any individual module that fails elaboration.

## Quick Start

From the repository root, install the tool into your active Python environment:
`python -m pip install ./lean-build-orchestrator`.
For a build or a shake, make the project’s Lean/Lake toolchain available. On Linux in
heuristic or always-overcommit mode, the scheduler uses available RAM and swap
as an estimate and still reports the raw commit counters separately.


```bash
cd lean-build-orchestrator

# 1. Read-only Windows commit & umbrella-import blast-radius audit
python -m lean_orch audit /path/to/lean-project

# 2. Commit-charge-aware topological build
python -m lean_orch build /path/to/lean-project --reserve-gb 3.0

# 3. Preview or apply `lake shake` with automatic backup + verify/rollback
python -m lean_orch shake /path/to/lean-project
python -m lean_orch shake /path/to/lean-project --fix

# 4. Full 2-phase pipeline (build -> shake -> verify)
python -m lean_orch pipeline /path/to/lean-project --fix
```

Incremental scheduling compares each module artifact with both its source and its local dependency artifacts. A separately rebuilt dependency invalidates older consumers transitively. Lake also checks the roots of the requested build even when local timestamps appear fresh. If import minimization fails verification, the orchestrator restores all changed sources in the backed-up target graph, checks the restored build, and returns a failure status for the rejected edit.
