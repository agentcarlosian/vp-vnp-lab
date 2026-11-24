"""Live Windows commit-charge and cross-platform memory introspection for Lean 4 builds."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import pathlib
import sys
from typing import Dict, Optional

GIB = 1024 ** 3


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


@dataclass(frozen=True)
class MemorySnapshot:
    platform: str
    physical_total_gb: float
    physical_avail_gb: float
    commit_total_gb: float
    commit_limit_gb: float
    commit_peak_gb: float
    page_size_bytes: int
    process_count: int
    source: str

    @property
    def commit_avail_gb(self) -> float:
        return max(0.0, self.commit_limit_gb - self.commit_total_gb)

    @property
    def commit_utilization_pct(self) -> float:
        if self.commit_limit_gb <= 0:
            return 0.0
        return 100.0 * self.commit_total_gb / self.commit_limit_gb

    def to_dict(self) -> Dict[str, object]:
        return {
            "platform": self.platform,
            "physical_total_gb": round(self.physical_total_gb, 3),
            "physical_avail_gb": round(self.physical_avail_gb, 3),
            "commit_total_gb": round(self.commit_total_gb, 3),
            "commit_limit_gb": round(self.commit_limit_gb, 3),
            "commit_avail_gb": round(self.commit_avail_gb, 3),
            "commit_peak_gb": round(self.commit_peak_gb, 3),
            "commit_utilization_pct": round(self.commit_utilization_pct, 2),
            "page_size_bytes": self.page_size_bytes,
            "process_count": self.process_count,
            "source": self.source,
        }

    def format_human(self) -> str:
        return (
            f"RAM {self.physical_avail_gb:.2f}/{self.physical_total_gb:.2f} GB free | "
            f"Commit {self.commit_total_gb:.2f}/{self.commit_limit_gb:.2f} GB used "
            f"(avail {self.commit_avail_gb:.2f} GB, peak {self.commit_peak_gb:.2f} GB, "
            f"{self.commit_utilization_pct:.1f}%) [{self.source}]"
        )


def get_memory_snapshot() -> MemorySnapshot:
    """Query OS commit-charge & physical memory (Win32 GetPerformanceInfo on Windows)."""
    if sys.platform == "win32":
        try:
            pi = _PERFORMANCE_INFORMATION()
            pi.cb = ctypes.sizeof(pi)
            if ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(pi), pi.cb):
                ps = int(pi.PageSize)
                return MemorySnapshot(
                    platform="win32",
                    physical_total_gb=pi.PhysicalTotal * ps / GIB,
                    physical_avail_gb=pi.PhysicalAvailable * ps / GIB,
                    commit_total_gb=pi.CommitTotal * ps / GIB,
                    commit_limit_gb=pi.CommitLimit * ps / GIB,
                    commit_peak_gb=pi.CommitPeak * ps / GIB,
                    page_size_bytes=ps,
                    process_count=int(pi.ProcessCount),
                    source="win32:GetPerformanceInfo",
                )
        except Exception:
            pass

    if os.path.exists("/proc/meminfo"):
        kv: Dict[str, float] = {}
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as fh:
                for line in fh:
                    if ":" in line:
                        k, rest = line.split(":", 1)
                        parts = rest.strip().split()
                        if parts and parts[0].isdigit():
                            kv[k.strip()] = int(parts[0]) * 1024.0 / GIB
            phys_tot = kv.get("MemTotal", 0.0)
            phys_av = kv.get("MemAvailable", kv.get("MemFree", 0.0))
            swap_tot = kv.get("SwapTotal", 0.0)
            commit_lim = kv.get("CommitLimit", phys_tot + swap_tot)
            commit_tot = kv.get("Committed_AS", phys_tot - phys_av)
            return MemorySnapshot(
                platform=sys.platform,
                physical_total_gb=phys_tot,
                physical_avail_gb=phys_av,
                commit_total_gb=commit_tot,
                commit_limit_gb=commit_lim,
                commit_peak_gb=commit_tot,
                page_size_bytes=4096,
                process_count=0,
                source="linux:/proc/meminfo",
            )
        except Exception:
            pass

    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        phys_tot = vm.total / GIB
        phys_av = vm.available / GIB
        commit_lim = (vm.total + sw.total) / GIB
        commit_tot = (vm.used + sw.used) / GIB
        return MemorySnapshot(
            platform=sys.platform,
            physical_total_gb=phys_tot,
            physical_avail_gb=phys_av,
            commit_total_gb=commit_tot,
            commit_limit_gb=commit_lim,
            commit_peak_gb=commit_tot,
            page_size_bytes=4096,
            process_count=len(psutil.pids()),
            source="psutil",
        )
    except Exception:
        return MemorySnapshot(
            platform=sys.platform,
            physical_total_gb=16.0,
            physical_avail_gb=8.0,
            commit_total_gb=8.0,
            commit_limit_gb=16.0,
            commit_peak_gb=8.0,
            page_size_bytes=4096,
            process_count=0,
            source="fallback-default",
        )


@dataclass(frozen=True)
class OleanFootprint:
    package_files: Dict[str, int]
    package_bytes: Dict[str, int]
    total_files: int
    total_bytes: int
    private_bytes: int
    server_bytes: int

    @property
    def total_gb(self) -> float:
        return self.total_bytes / GIB

    @property
    def private_gb(self) -> float:
        return self.private_bytes / GIB

    def estimated_windows_commit_per_umbrella_worker_gb(self) -> float:
        """Estimate commit charge for a Lean 4 worker importing the entire package closure.

        On Windows, Lean memory-maps `.olean` and `.olean.private` artifacts plus allocates
        elaboration heaps and environment hash tables. Empirically on Lean 4.33 + Mathlib
        (~5.3 GB of `.olean*` files across 52k files), a single `import Mathlib` worker
        commits ~9.5-10.5 GB of Windows pagefile commit charge (~1.75x mapped + 1.0 GB).
        """
        mapped = (self.total_bytes - self.server_bytes) / GIB
        if mapped < 0.2:
            return 0.45
        return round(max(1.0, mapped * 1.75 + 1.0), 2)

    def to_dict(self) -> Dict[str, object]:
        return {
            "total_files": self.total_files,
            "total_gb": round(self.total_gb, 3),
            "private_gb": round(self.private_gb, 3),
            "server_gb": round(self.server_bytes / GIB, 3),
            "estimated_umbrella_worker_commit_gb": self.estimated_windows_commit_per_umbrella_worker_gb(),
            "packages_gb": {
                k: round(v / GIB, 3) for k, v in sorted(self.package_bytes.items(), key=lambda kv: -kv[1])
            },
            "packages_files": dict(sorted(self.package_files.items(), key=lambda kv: -kv[1])),
        }


def measure_olean_footprint(project_root: pathlib.Path) -> OleanFootprint:
    """Measure on-disk `.olean*` footprint across `.lake/packages` and local `.lake/build`."""
    pkg_files: Dict[str, int] = {}
    pkg_bytes: Dict[str, int] = {}
    total_files = 0
    total_bytes = 0
    private_bytes = 0
    server_bytes = 0

    roots: list[tuple[str, pathlib.Path]] = []
    local_build = project_root / ".lake" / "build" / "lib" / "lean"
    if local_build.exists():
        roots.append(("<local>", local_build))

    pkgs_dir = project_root / ".lake" / "packages"
    if pkgs_dir.exists():
        for pkg in sorted(pkgs_dir.iterdir()):
            lean_lib = pkg / ".lake" / "build" / "lib" / "lean"
            if lean_lib.exists():
                roots.append((pkg.name, lean_lib))

    for name, directory in roots:
        cnt = 0
        b_sum = 0
        for fp in directory.rglob("*.olean*"):
            try:
                sz = fp.stat().st_size
            except OSError:
                continue
            cnt += 1
            b_sum += sz
            total_files += 1
            total_bytes += sz
            if fp.name.endswith(".olean.private"):
                private_bytes += sz
            elif fp.name.endswith(".olean.server"):
                server_bytes += sz
        if cnt:
            pkg_files[name] = cnt
            pkg_bytes[name] = b_sum

    return OleanFootprint(
        package_files=pkg_files,
        package_bytes=pkg_bytes,
        total_files=total_files,
        total_bytes=total_bytes,
        private_bytes=private_bytes,
        server_bytes=server_bytes,
    )


def estimate_safe_workers(
    avail_commit_gb: float,
    per_worker_gb: float,
    reserve_gb: float = 3.0,
    max_cap: Optional[int] = None,
) -> int:
    """Compute how many simultaneous workers fit inside available commit charge."""
    usable = max(0.0, avail_commit_gb - reserve_gb)
    if per_worker_gb <= 0:
        workers = max_cap or 1
    else:
        workers = max(1, int(usable // per_worker_gb)) if usable >= per_worker_gb * 0.7 else 1
    if max_cap is not None:
        workers = min(workers, max(1, max_cap))
    return workers
