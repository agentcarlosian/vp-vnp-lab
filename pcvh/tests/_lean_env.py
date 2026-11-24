"""Portable Lean 4 toolchain detection for PCVH pytest suites (Windows, Linux, macOS)."""

from __future__ import annotations

import os
import pathlib
from typing import Optional

from pcvh.tcb.palomar_gate import resolve_lean_bin

LAKE_EXE_NAME = "lake.exe" if os.name == "nt" else "lake"


def detect_lean_bin(project_root: pathlib.Path) -> Optional[pathlib.Path]:
    env_override = os.environ.get("PCVH_LEAN_BIN")
    if env_override:
        cand = pathlib.Path(env_override)
        if (cand / LAKE_EXE_NAME).exists():
            return cand
    try:
        return resolve_lean_bin(project_root)
    except FileNotFoundError:
        return None
