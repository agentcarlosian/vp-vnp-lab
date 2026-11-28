"""Check a complete, independently pinned case transcript and replay it in Lean."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from ..config import SpecConfig, load_spec_config
from .manifest import ManifestVerification, sha256_file, stage_project_files

ORACLE = "conformance-oracle.lean.in"
MAX_BYTES = 16 * 1024 * 1024


def check_policy(cfg: SpecConfig) -> None:
    if (type(cfg.conformance_traces) is not int or cfg.conformance_traces <= 0
            or not isinstance(cfg.conformance_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", cfg.conformance_sha256)):
        raise ValueError("Conformance requires a reviewed trace count and transcript_sha256 in pcvh.toml")


def check_transcript(cfg: SpecConfig, raw: bytes) -> bytes:
    check_policy(cfg)
    data = raw.replace(b"\r\n", b"\n")
    if len(raw) > MAX_BYTES or not data.endswith(b"\n"):
        raise ValueError("Missing, truncated or oversized conformance transcript")
    count = data.count(b"\n")
    if count != cfg.conformance_traces or data.startswith(b"\n") or b"\n\n" in data:
        raise ValueError(f"Expected {cfg.conformance_traces} complete case records, received {count}")
    if hashlib.sha256(data).hexdigest() != cfg.conformance_sha256:
        raise ValueError("Case inputs or results differ from the reviewed transcript")
    return data


def confirmed_summary(cfg: SpecConfig, output: str) -> str:
    summary = output.strip()
    n = cfg.conformance_traces
    if not re.fullmatch(fr"{n}/{n} [^\r\n]*matched bit-for-bit", summary):
        raise ValueError("Lean oracle did not confirm the complete reviewed case count")
    return summary


def capture_records(command: str | list[str], *, cwd: Path, env: dict[str, str] | None = None,
                    shell: bool = False) -> bytes:
    with subprocess.Popen(command, cwd=cwd, env=env, shell=shell, stdout=subprocess.PIPE) as proc:
        assert proc.stdout is not None
        data = proc.stdout.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            proc.kill()
            raise ValueError("Conformance transcript exceeds size limit")
        if proc.wait() != 0:
            raise ValueError("Conformance case producer failed")
    return data


def produce(cfg: SpecConfig, lean_bin: Path) -> bytes:
    if not cfg.conformance_command:
        raise ValueError("No conformance producer configured")
    env = dict(os.environ, PCVH_EMIT_TRACES="1", PCVH_LEAN_BIN=str(lean_bin),
               PCVH_OVERLAY_WS=str(cfg.project_root), PYTHONIOENCODING="utf-8")
    return capture_records(cfg.conformance_command, shell=True, cwd=cfg.project_root, env=env)


def stage_oracle(root: Path, manifest: ManifestVerification, dest: Path) -> None:
    if not manifest.ok or ORACLE not in manifest.file_hashes:
        raise ValueError("The independent Lean conformance oracle must be pinned")
    dest.mkdir()
    for rel, digest in manifest.file_hashes.items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / rel, target)
        if sha256_file(target) != digest:
            raise ValueError(f"Conformance policy changed during staging: {rel}")


def replay(cfg: SpecConfig, data: bytes, lean_bin: Path) -> str:
    """Build only the reviewed specification and run the reviewed oracle on data."""
    data = check_transcript(cfg, data)
    root = cfg.project_root
    (root / "pcvh-traces.txt").write_bytes(data)
    script = (root / ORACLE).read_text(encoding="utf-8").replace("{DATA_FILE}", "pcvh-traces.txt")
    lake = lean_bin / ("lake.exe" if os.name == "nt" else "lake")
    env = dict(os.environ, PATH=str(lean_bin) + os.pathsep + os.environ.get("PATH", ""))
    statement = Path(cfg.statement_rel).with_suffix("").as_posix().replace("/", ".")
    for args, source in [(["build", statement], None), (["env", "lean", "--stdin"], script)]:
        run = subprocess.run([str(lake), *args], cwd=root, env=env, input=source, capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=600)
        if run.returncode:
            raise ValueError(f"Lean conformance oracle failed: {(run.stdout + run.stderr)[-600:]}")
    return confirmed_summary(cfg, run.stdout)


if __name__ == "__main__":
    # Internal Docker entry point. The host supplies separate read-only input
    # mounts for the producer and the oracle, each with its own writable tmpfs.
    mode, source = sys.argv[1:]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "workspace"
        stage_project_files(Path(source), root, include_lake_manifest=True)
        cfg = load_spec_config(root)
        if mode == "emit":
            sys.stdout.buffer.write(produce(cfg, Path("/opt/lean/bin")))
        elif mode == "replay":
            print(replay(cfg, sys.stdin.buffer.read(MAX_BYTES + 1), Path("/opt/lean/bin")))
        else:
            raise ValueError("Unknown conformance worker mode")
