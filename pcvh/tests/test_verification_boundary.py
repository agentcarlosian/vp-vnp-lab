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
    production = project / "prod_vault.py"
    original = production.read_bytes()
    production.write_text("# Implementation unavailable", encoding="utf-8")
    rejected = verify_isolated(project, image=image, expected_digest=reviewed.spec_bundle_sha256)
    assert rejected["verdict"] == "REJECTED"
    assert rejected["checks"]["differential_conformance"].startswith("FAIL")
    proof_only = verify_isolated(project, image=image, expected_digest=reviewed.spec_bundle_sha256,
                                 conformance=False)
    assert proof_only["verdict"] == "VERIFIED"
    assert proof_only["checks"]["differential_conformance"] == "SKIPPED_BY_REQUEST"
    production.write_bytes(original)
    policy = project / "pcvh.toml"
    policy.write_text(policy.read_text() + "\n# revised policy\n")
    pin_tcb_manifest(load_spec_config(project))
    rejected = verify_isolated(project, image=image, expected_digest=reviewed.spec_bundle_sha256)
    assert rejected["verdict"] == "REJECTED"
    assert "lean_kernel_build" not in rejected["checks"]


def test_conformance_requires_every_reviewed_case_in_order():
    import hashlib
    from types import SimpleNamespace
    from pcvh.tcb.conformance import check_transcript

    expected = b"first|1\nsecond|2\n"
    cfg = SimpleNamespace(conformance_traces=2, conformance_sha256=hashlib.sha256(expected).hexdigest())
    assert check_transcript(cfg, expected.replace(b"\n", b"\r\n")) == expected
    for incomplete in (b"", b"2/2 test cases passed\n", b"first|1\n", b"first|1\nfirst|1\n",
                       b"second|2\nfirst|1\n", b"first|1\nsecond|3\n", expected + b"extra|3\n"):
        with pytest.raises(ValueError):
            check_transcript(cfg, incomplete)


def test_studio_keeps_signing_material_outside_served_projects(project, tmp_path, monkeypatch):
    from pcvh.studio.server import StudioState
    state = StudioState(project)
    monkeypatch.setenv("PCVH_STUDIO_KEY_DIR", str(tmp_path / "user-keys"))
    legacy = project / ".pcvh_studio_keys"
    legacy.mkdir()
    (legacy / "pcvh_signing.key.pem").write_text("old private fixture")
    signed = state.sign_project_attestation(".")
    assert state.verify_project_signature(".", signed["public_key_pem"])["ok"]
    assert state.sign_project_attestation(".")["key_id"] == signed["key_id"]
    assert len(list((tmp_path / "user-keys").rglob("*.key.pem"))) == 1
    assert state.read_project_file(".", "Solution.lean")
    for private in (".pcvh_studio_keys/pcvh_signing.key.pem", "pcvh_signing.key.pem", ".git/config"):
        with pytest.raises(ValueError):
            state.read_project_file(".", private)
        with pytest.raises(ValueError):
            state.save_project_file(".", private, "fixture")
    assert ".pcvh_studio_keys/pcvh_signing.key.pem" not in state.get_project_detail(".")["files"]
    monkeypatch.setenv("PCVH_STUDIO_KEY_DIR", str(project / "keys"))
    with pytest.raises(ValueError, match="outside"):
        state.sign_project_attestation(".")

def test_reviewed_digest_alone_does_not_pass_lean_oracle(project, tmp_path):
    import hashlib
    from tests._lean_env import detect_lean_bin
    from pcvh.tcb.conformance import replay, stage_oracle

    tools = detect_lean_bin(project)
    if tools is None:
        pytest.skip("Lean 4 toolchain missing")
    policy = load_spec_config(project)
    oracle = tmp_path / "oracle"
    stage_oracle(project, verify_tcb_manifest(policy), oracle)
    assert not (oracle / "prod_vault.py").exists()
    cfg = load_spec_config(oracle)
    data = b"10|10|0|0|0|0|10|10|0|0|0\n"
    cfg.conformance_traces = 1
    cfg.conformance_sha256 = hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError, match="MISMATCH"):
        replay(cfg, data, tools)
