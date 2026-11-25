"""Run a verifier-selected PCVH image without host execution or writable host mounts."""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from .manifest import stage_project_files


def verify_isolated(project: Path, *, image: str, expected_digest: str,
                    conformance: bool = True, dual_kernel: bool = False) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest or ""):
        raise ValueError("Supply --expected-spec-sha256 from an independently reviewed pin.")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image or ""):
        raise ValueError("Supply the local verifier image ID (sha256:...) with --sandbox-image.")
    root = project.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Candidate must be a directory.")
    # Windows executable lookup can implicitly search the current directory.
    # Only consider explicit, absolute PATH entries outside the candidate.
    executable = "docker.exe" if os.name == "nt" else "docker"
    docker = None
    for directory in os.get_exec_path():
        if Path(directory).is_absolute():
            binary = (Path(directory) / executable).resolve()
            if not binary.is_relative_to(root) and binary.is_file() and os.access(binary, os.X_OK):
                docker = str(binary)
                break
    if docker is None:
        raise ValueError("Docker is required on a trusted PATH for isolated verification.")
    with tempfile.TemporaryDirectory(prefix="pcvh_inputs_") as tmp:
        inputs = Path(tmp) / "source"
        stage_project_files(root, inputs, include_lake_manifest=True)
        # The private parent protects host access. The container reads its
        # bind mount as a different, unprivileged UID.
        inputs.chmod(0o755)
        for entry in inputs.rglob("*"):
            entry.chmod(0o755 if entry.is_dir() or entry.stat().st_mode & 0o111 else 0o644)
        return _run_image(docker, inputs, image, expected_digest, conformance, dual_kernel)


def _run_image(docker: str, root: Path, image: str, expected_digest: str, conformance: bool,
               dual_kernel: bool) -> dict:
    mount = io.StringIO()
    csv.writer(mount).writerow(["type=bind", f"source={root}", "target=/candidate",
                                "readonly", "bind-recursive=disabled"])
    cmd = [
        docker, "run", "--rm", "--pull=never", "--network=none", "--read-only",
        "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=65534:65534",
        "--pids-limit=256", "--memory=4g", "--cpus=2", "--ulimit", "core=0",
        "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=2g,mode=1777",
        "--env", "HOME=/tmp", "--mount", mount.getvalue().rstrip(),
        "--log-driver=none", "--workdir=/", "--entrypoint=/usr/bin/timeout", image,
        "--signal=KILL", "900", "/usr/local/bin/python",
        "-I", "-m", "pcvh", "verify", "/candidate", "--trusted-local",
        "--lean-bin", "/opt/lean/bin", "--expected-spec-sha256", expected_digest,
        "--attestation", "/tmp/result.json", "--json",
    ]
    if not conformance:
        cmd.append("--skip-conformance")
    if dual_kernel:
        cmd.append("--require-dual-kernel")
    try:
        run = subprocess.run(cmd, cwd=root.parent, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=960)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Isolated verification timed out.") from exc
    if run.returncode not in (0, 1) or not run.stdout.strip():
        raise ValueError(f"Isolated verifier failed ({run.returncode}): {run.stderr[-1000:]}")
    report = json.loads(run.stdout)
    if not isinstance(report, dict) or report.get("schema") != "pcvh.attestation.v1":
        raise ValueError("Isolated verifier returned an invalid attestation.")
    if run.returncode == 0 and (report.get("verdict") != "VERIFIED"
                                or report.get("spec_bundle_sha256") != expected_digest):
        raise ValueError("Isolated verifier returned an inconsistent success result.")
    if run.returncode == 1 and report.get("verdict") != "REJECTED":
        raise ValueError("Isolated verifier did not return a rejection.")
    return report
