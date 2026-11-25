"""SHA-256 TCB manifest pinning and immutable overlay workspace construction."""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import hashlib
import json
import os
import pathlib
import stat
import shutil
from typing import Dict, List, Optional, Tuple

from ..config import SpecConfig

LOCK_FILENAME = "spec.lock.json"
TCB_SNAPSHOT_DIR = ".pcvh_tcb_snapshot"


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    # Normalize CRLF -> LF when hashing text spec files so Windows/Linux CI match identically
    data = path.read_bytes()
    if path.name == "lean-toolchain" or path.suffix in {".py", ".lean", ".toml", ".json"}:
        data = data.replace(b"\r\n", b"\n")
    h.update(data)
    return h.hexdigest()


def _bundle_digest(hashes: Dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode("utf-8")).hexdigest()


def _regular_path(root: pathlib.Path, rel: str) -> pathlib.Path:
    path = pathlib.PurePosixPath(rel)
    if (not path.parts or pathlib.PureWindowsPath(rel).anchor or ".." in path.parts
            or path.as_posix() != rel or "\\" in rel or ":" in rel):
        raise ValueError(f"Invalid manifest path: {rel}")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink() or getattr(current.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError(f"Linked manifest path: {rel}")
    if not current.is_file():
        raise ValueError(f"Expected a regular file: {rel}")
    return current


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
        norm_rel = rel.replace("\\", "/")
        fp = _regular_path(cfg.project_root, norm_rel)
        file_hashes[norm_rel] = sha256_file(fp)
        if save_snapshot:
            dest = snap_dir / norm_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fp, dest)

    bundle = _bundle_digest(file_hashes)

    lock_payload = {
        "schema": "pcvh.spec-lock.v2",
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

    mismatched: List[str] = []
    missing: List[str] = []
    actual: Dict[str, str] = {}
    try:
        lock = json.loads(_regular_path(cfg.project_root, LOCK_FILENAME).read_text(encoding="utf-8"))
        if not isinstance(lock, dict) or lock.get("schema") != "pcvh.spec-lock.v2":
            raise ValueError("Re-pin the reviewed specification to create a v2 lock")
        expected = lock.get("files")
        if not isinstance(expected, dict):
            raise ValueError("Invalid manifest file table")
        required = {rel.replace("\\", "/") for rel in cfg.tcb_rel_paths}
        # Lake generates this during ordinary builds. An unpinned generated
        # manifest is discarded when staging, so it cannot control verification.
        if "lake-manifest.json" not in expected and "lake-manifest.json" not in cfg.extra_tcb_files:
            required.discard("lake-manifest.json")
        if set(expected) != required:
            raise ValueError("Manifest file set differs from the required policy inputs")
        for rel in sorted(required):
            try:
                actual[rel] = sha256_file(_regular_path(cfg.project_root, rel))
            except FileNotFoundError:
                missing.append(rel)
                continue
            if actual[rel] != expected[rel]:
                mismatched.append(rel)
        if lock.get("spec_bundle_sha256") != _bundle_digest(actual):
            mismatched.append("spec_bundle_sha256")
    except (OSError, ValueError) as exc:
        mismatched.append(str(exc))
    return ManifestVerification(not (mismatched or missing), True, _bundle_digest(actual),
                                mismatched, missing, actual)


def stage_project_files(project_root: pathlib.Path, dest_dir: pathlib.Path, *, include_lake_manifest: bool) -> None:
    """Copy ordinary project inputs, omitting local caches, VCS metadata and PCVH keys."""
    if dest_dir.resolve().is_relative_to(project_root.resolve()):
        raise ValueError("Choose a project separate from the verifier temporary directory")
    dest_dir.mkdir(parents=True, exist_ok=True)
    skip_dirs = {
        ".lake",
        ".git",
        "__pycache__",
        ".pytest_cache",
        TCB_SNAPSHOT_DIR,
        ".lean-orch-backups",
        "target",
        "node_modules",
        "out",
        "cache",
        "broadcast",
    }

    skip_dirs.update({".elan", ".pcvh_studio_keys", ".keys", ".venv", "venv"})
    for base, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        parent = pathlib.Path(base)
        for name in dirs:
            entry = parent / name
            if entry.is_symlink() or getattr(entry.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError(f"Linked directory in candidate: {name}")
        for name in files:
            if name.endswith(".key.pem") or name == ".git":
                continue
            rel = (parent / name).relative_to(project_root).as_posix()
            if rel == "lake-manifest.json" and not include_lake_manifest:
                continue
            source = _regular_path(project_root, rel)
            target = dest_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            shutil.copymode(source, target)


def build_isolated_overlay_workspace(
    cfg: SpecConfig,
    dest_dir: pathlib.Path,
    manifest: ManifestVerification,
    trusted_tcb_source: Optional[pathlib.Path] = None,
) -> Tuple[pathlib.Path, List[str]]:
    """Construct a clean sandboxed copy of untrusted proof files overlaid with immutable TCB files.

    Returns (workspace_path, overlaid_tcb_files).
    """
    stage_project_files(cfg.project_root, dest_dir, include_lake_manifest="lake-manifest.json" in manifest.file_hashes)
    # Recheck the actual staged bytes before any executable consumes them.
    overlaid: List[str] = []
    for rel, digest in manifest.file_hashes.items():
        dest = dest_dir / rel
        if trusted_tcb_source is not None:
            shutil.copyfile(_regular_path(trusted_tcb_source, rel), dest)
            overlaid.append(rel)
        if sha256_file(dest) != digest:
            raise ValueError(f"TCB content changed during staging: {rel}")
    return dest_dir, overlaid
