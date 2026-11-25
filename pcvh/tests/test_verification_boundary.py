"""Policy and execution boundary regressions using an ordinary local blueprint."""

import json
import os
import pathlib
import shutil

import pytest

from pcvh.config import load_spec_config
from pcvh.tcb import palomar_gate
from pcvh.tcb.isolated import verify_isolated
from pcvh.tcb.manifest import pin_tcb_manifest, verify_tcb_manifest


@pytest.fixture
def project(tmp_path):
    source = pathlib.Path(__file__).resolve().parents[1] / "blueprints" / "01_erc4626_vault"
    return shutil.copytree(source, tmp_path / "candidate")


@pytest.mark.parametrize("change", ["native_default", "digest", "file_set", "static", "new_policy"])
def test_preflight_denies_execution(project, monkeypatch, change):
    cfg = load_spec_config(project)
    digest = verify_tcb_manifest(cfg).spec_bundle_sha256
    if change in ("digest", "file_set"):
        lock = project / "spec.lock.json"
        data = json.loads(lock.read_text())
        if change == "digest":
            data["spec_bundle_sha256"] = "0" * 64
        else:
            del data["files"]["pcvh.toml"]
        lock.write_text(json.dumps(data))
    elif change == "static":
        (project / "Solution.lean").write_text("theorem incomplete : True := by sorry")
    elif change == "new_policy":
        policy = project / "pcvh.toml"
        policy.write_text(policy.read_text() + "\n# independently changed version\n")
        cfg = load_spec_config(project)
        pin_tcb_manifest(cfg)
        assert verify_tcb_manifest(cfg).ok
    monkeypatch.setattr(palomar_gate, "resolve_lean_bin", lambda *a: pytest.fail("started native execution"))
    saved = project / "proof-attestation.json"
    result = palomar_gate.run_palomar_gate(cfg, trusted_local=change != "native_default",
                                          expected_spec_sha256=digest, attestation_out=saved)
    if change != "native_default":
        assert json.loads(saved.read_text())["verdict"] == "REJECTED"
    assert result.verdict == "REJECTED"
    if change == "static":
        assert "sorry" in result.failure_reasons[0]


def test_isolated_verifier_requires_external_inputs_before_docker(project, monkeypatch):
    monkeypatch.setattr(os, "get_exec_path", lambda *a: pytest.fail("looked up executable"))
    with pytest.raises(ValueError, match="reviewed pin"):
        verify_isolated(project, image="", expected_digest="")
    with pytest.raises(ValueError, match="image ID"):
        verify_isolated(project, image="latest", expected_digest="a" * 64)

def test_candidate_cannot_supply_docker(project, monkeypatch):
    name = "docker.exe" if os.name == "nt" else "docker"
    local = project / name
    local.write_text("test fixture")
    local.chmod(0o755)
    monkeypatch.setattr(os, "get_exec_path", lambda: [".", str(project)])
    with pytest.raises(ValueError, match="trusted PATH"):
        verify_isolated(project, image="sha256:" + "b" * 64, expected_digest="a" * 64)


def test_isolated_mount_contains_only_staged_project_inputs(project, monkeypatch):
    from pcvh.tcb import isolated

    (project / ".keys").mkdir()
    (project / ".keys" / "dummy.txt").write_text("test marker")
    (project / "local.key.pem").write_text("test marker")
    # Provide an inert CLI file in a verifier-controlled sibling directory.
    tools_dir = project.parent / "tools"
    tools_dir.mkdir()
    cli = tools_dir / ("docker.exe" if os.name == "nt" else "docker")
    cli.touch(mode=0o755)
    monkeypatch.setattr(os, "get_exec_path", lambda: [str(tools_dir)])

    def inspect_inputs(docker, root, image, expected_digest, conformance, dual_kernel):
        assert root != project and (root / "Solution.lean").is_file()
        assert not (root / ".keys").exists()
        assert not (root / "local.key.pem").exists()
        return {"checked": True}

    monkeypatch.setattr(isolated, "_run_image", inspect_inputs)
    assert verify_isolated(project, image="sha256:" + "b" * 64, expected_digest="a" * 64)["checked"]


@pytest.mark.skipif(not os.environ.get("PCVH_TEST_IMAGE"), reason="requires the local verifier image")
def test_isolated_blueprint_and_independent_pin(project):
    # The trusted reference and external digest are established before submitting the candidate.
    cfg = load_spec_config(project)
    reviewed = verify_tcb_manifest(cfg)
    assert reviewed.ok
    image = os.environ["PCVH_TEST_IMAGE"]
    result = verify_isolated(project, image=image, expected_digest=reviewed.spec_bundle_sha256)
    assert result["verdict"] == "VERIFIED", result["failure_reasons"]
    assert "1000/1000" in result["checks"]["differential_conformance"]
    policy = project / "pcvh.toml"
    policy.write_text(policy.read_text() + "\n# revised policy\n")
    pin_tcb_manifest(load_spec_config(project))
    rejected = verify_isolated(project, image=image, expected_digest=reviewed.spec_bundle_sha256)
    assert rejected["verdict"] == "REJECTED"
    assert "lean_kernel_build" not in rejected["checks"]
