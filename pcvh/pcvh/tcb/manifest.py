"""SHA-256 TCB manifest pinning and immutable overlay workspace construction."""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import hashlib
import json
import pathlib
import shutil
from typing import Dict, List, Optional, Tuple

from ..config import SpecConfig

LOCK_FILENAME = "spec.lock.json"
TCB_SNAPSHOT_DIR = ".pcvh_tcb_snapshot"


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    # Normalize CRLF -> LF when hashing text spec files so Windows/Linux CI match identically
    data = path.read_bytes().replace(b"\r\n", b"\n")
    h.update(data)
    return h.hexdigest()


@dataclass
class ManifestVerification:
    ok: bool
    lock_exists: bool
    spec_bundle_sha256: str
    mismatched_files: List[str]
    missing_files: List[str]
    file_hashes: Dict[str, str]


def pin_tcb_manifest(cfg: SpecConfig, save_snapshot: bool = True) -> Dict[str, object]:
    """Pin all TCB files into `spec.lock.json` and an immutable local snapshot directory."""
    file_hashes: Dict[str, str] = {}
    snap_dir = cfg.project_root / TCB_SNAPSHOT_DIR
    if save_snapshot:
        if snap_dir.exists():
            shutil.rmtree(snap_dir)
        snap_dir.mkdir(parents=True, exist_ok=True)

    for rel in cfg.tcb_rel_paths:
        fp = cfg.project_root / rel
        if not fp.exists():
            raise FileNotFoundError(f"TCB file missing during pin: {fp}")
        norm_rel = rel.replace("\\", "/")
        file_hashes[norm_rel] = sha256_file(fp)
        if save_snapshot:
            dest = snap_dir / norm_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fp, dest)

    bundle = hashlib.sha256(
        json.dumps(file_hashes, sort_keys=True).encode("utf-8")
    ).hexdigest()

    lock_payload = {
        "schema": "pcvh.spec-lock.v1",
        "name": cfg.name,
        "pinned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "spec_bundle_sha256": bundle,
        "files": file_hashes,
    }
    lock_path = cfg.project_root / LOCK_FILENAME
    lock_path.write_text(json.dumps(lock_payload, indent=2) + "\n", encoding="utf-8")
    return lock_payload


def verify_tcb_manifest(cfg: SpecConfig) -> ManifestVerification:
    """Compare current working-tree TCB files against `spec.lock.json`."""
    lock_path = cfg.project_root / LOCK_FILENAME
    if not lock_path.exists():
        return ManifestVerification(
            ok=False,
            lock_exists=False,
            spec_bundle_sha256="",
            mismatched_files=[],
            missing_files=[LOCK_FILENAME],
            file_hashes={},
        )

    lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
    expected: Dict[str, str] = lock_data.get("files", {})
    mismatched: List[str] = []
    missing: List[str] = []
    actual_hashes: Dict[str, str] = {}

    for rel, exp_hash in expected.items():
        fp = cfg.project_root / rel
        if not fp.exists():
            missing.append(rel)
            continue
        act = sha256_file(fp)
        actual_hashes[rel] = act
        if act != exp_hash:
            mismatched.append(rel)

    return ManifestVerification(
        ok=(not mismatched and not missing),
        lock_exists=True,
        spec_bundle_sha256=str(lock_data.get("spec_bundle_sha256", "")),
        mismatched_files=mismatched,
        missing_files=missing,
        file_hashes=expected,
    )


def build_isolated_overlay_workspace(
    cfg: SpecConfig,
    dest_dir: pathlib.Path,
    trusted_tcb_source: Optional[pathlib.Path] = None,
) -> Tuple[pathlib.Path, List[str]]:
    """Construct a clean sandboxed copy of untrusted proof files overlaid with immutable TCB files.

    Returns (workspace_path, overlaid_tcb_files).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    skip_dirs = {".lake", ".git", "__pycache__", ".pytest_cache", TCB_SNAPSHOT_DIR, ".lean-orch-backups"}

    # 1. Copy untrusted candidate project files (excluding build artifacts & snapshot)
    for item in cfg.project_root.rglob("*"):
        rel = item.relative_to(cfg.project_root)
        if any(part in skip_dirs for part in rel.parts):
            continue
        target = dest_dir / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)

    # 2. Force-overwrite all TCB files from trusted source (snapshot or explicit TCB directory)
    tcb_src = trusted_tcb_source or (cfg.project_root / TCB_SNAPSHOT_DIR)
    overlaid: List[str] = []
    if tcb_src.exists():
        lock_path = cfg.project_root / LOCK_FILENAME
        expected = json.loads(lock_path.read_text(encoding="utf-8")).get("files", {}) if lock_path.exists() else {}
        for rel, exp_hash in expected.items():
            src_fp = tcb_src / rel
            if not src_fp.exists():
                raise FileNotFoundError(f"Trusted TCB snapshot missing file: {src_fp}")
            if sha256_file(src_fp) != exp_hash:
                raise RuntimeError(f"Trusted TCB snapshot corrupted for {rel} (SHA-256 mismatch!)")
            dst_fp = dest_dir / rel
            dst_fp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_fp, dst_fp)
            overlaid.append(rel)

    return dest_dir, overlaid
