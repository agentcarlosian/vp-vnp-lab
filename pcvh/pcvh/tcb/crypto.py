"""Cryptographic Attestation Hardening: Ed25519 DSSE Envelopes & Optional Sigstore Cosign."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

DSSE_PAYLOAD_TYPE = "application/vnd.pcvh.attestation.v1+json"


@dataclass
class KeyPairInfo:
    private_key_path: pathlib.Path
    public_key_path: pathlib.Path
    key_id: str
    public_key_pem: str


@dataclass
class SignatureVerificationResult:
    ok: bool
    algorithm: str
    key_id: str
    attestation_sha256: str
    reason: str = "PASS"

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "attestation_sha256": self.attestation_sha256,
            "reason": self.reason,
        }


def compute_public_key_id(public_key_pem: bytes | str) -> str:
    raw = public_key_pem.encode("utf-8") if isinstance(public_key_pem, str) else public_key_pem
    pub = serialization.load_pem_public_key(raw)
    if not isinstance(pub, Ed25519PublicKey):
        raise ValueError("Expected an Ed25519 public key in PEM format.")
    pub_bytes = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "ed25519:" + hashlib.sha256(pub_bytes).hexdigest()[:16]


def generate_ed25519_keypair(
    out_dir: pathlib.Path,
    *,
    prefix: str = "pcvh_signing",
) -> KeyPairInfo:
    """Generate a fresh Ed25519 keypair in PEM format and return paths + fingerprint `key_id`."""
    out = pathlib.Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()

    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    priv_path = out / f"{prefix}.key.pem"
    pub_path = out / f"{prefix}.pub.pem"
    if os.name != "nt":
        fd = os.open(priv_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(priv_pem)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        os.chmod(priv_path, 0o600)
    else:
        priv_path.write_bytes(priv_pem)
    pub_path.write_bytes(pub_pem)

    key_id = compute_public_key_id(pub_pem)
    return KeyPairInfo(
        private_key_path=priv_path,
        public_key_path=pub_path,
        key_id=key_id,
        public_key_pem=pub_pem.decode("utf-8"),
    )


def _canonical_attestation_body(attestation: Dict[str, Any]) -> Dict[str, Any]:
    """Strip mutable signature fields to obtain the canonical attestation payload covered by SHA-256 & DSSE."""
    return {
        k: v
        for k, v in attestation.items()
        if k not in ("attestation_sha256", "signature_envelope", "cosign_bundle")
    }


def _canonical_json_bytes(obj: Dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _dsse_pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE Pre-Authentication Encoding (PAE) per Secure Systems Lab / Sigstore in-toto DSSE v1."""
    pt_bytes = payload_type.encode("utf-8")
    return b"DSSEv1 %d %b %d %b" % (len(pt_bytes), pt_bytes, len(payload), payload)


def sign_attestation_ed25519(
    attestation: Dict[str, Any],
    private_key_pem: bytes | str,
    *,
    key_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Sign a PCVH proof attestation dict using Ed25519 inside a DSSE v1 envelope (in-place copy returned)."""
    raw_pem = private_key_pem.encode("utf-8") if isinstance(private_key_pem, str) else private_key_pem
    priv = serialization.load_pem_private_key(raw_pem, password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        raise ValueError("Private key must be an Ed25519 key in PEM format.")

    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    resolved_key_id = key_id or compute_public_key_id(pub_pem)

    body = _canonical_attestation_body(attestation)
    # Recompute canonical SHA-256 (compatible with palomar_gate.py's sorted-keys JSON hash)
    att_sha = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()

    payload_obj = dict(body)
    payload_obj["attestation_sha256"] = att_sha
    payload_bytes = _canonical_json_bytes(payload_obj)
    pae = _dsse_pae(DSSE_PAYLOAD_TYPE, payload_bytes)
    sig_bytes = priv.sign(pae)

    signed = dict(body)
    signed["attestation_sha256"] = att_sha
    signed["signature_envelope"] = {
        "schema": "dsse.v1",
        "payloadType": DSSE_PAYLOAD_TYPE,
        "payload": base64.b64encode(payload_bytes).decode("ascii"),
        "signatures": [
            {
                "keyid": resolved_key_id,
                "alg": "Ed25519",
                "sig": base64.b64encode(sig_bytes).decode("ascii"),
            }
        ],
    }
    return signed


def verify_attestation_signature(
    attestation: Dict[str, Any],
    public_key_pem: bytes | str,
) -> SignatureVerificationResult:
    """Cryptographically verify a signed PCVH attestation against an Ed25519 PEM public key."""
    raw_pub = public_key_pem.encode("utf-8") if isinstance(public_key_pem, str) else public_key_pem
    try:
        pub = serialization.load_pem_public_key(raw_pub)
    except Exception as exc:
        return SignatureVerificationResult(False, "Ed25519", "", "", f"Invalid public key PEM: {exc}")
    if not isinstance(pub, Ed25519PublicKey):
        return SignatureVerificationResult(False, "Ed25519", "", "", "Public key is not Ed25519.")

    expected_key_id = compute_public_key_id(raw_pub)
    body = _canonical_attestation_body(attestation)
    recomputed_sha = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
    claimed_sha = str(attestation.get("attestation_sha256", ""))
    if claimed_sha != recomputed_sha:
        return SignatureVerificationResult(
            False,
            "Ed25519",
            expected_key_id,
            recomputed_sha,
            f"Attestation SHA-256 tamper detected (claimed={claimed_sha[:16]}, actual={recomputed_sha[:16]})",
        )

    env = attestation.get("signature_envelope")
    if not isinstance(env, dict):
        return SignatureVerificationResult(False, "Ed25519", expected_key_id, recomputed_sha, "Missing signature_envelope")

    pt = str(env.get("payloadType", ""))
    if pt != DSSE_PAYLOAD_TYPE:
        return SignatureVerificationResult(False, "Ed25519", expected_key_id, recomputed_sha, f"Unexpected payloadType: {pt}")

    try:
        payload_bytes = base64.b64decode(str(env.get("payload", "")), validate=True)
        payload_obj = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        return SignatureVerificationResult(False, "Ed25519", expected_key_id, recomputed_sha, f"Malformed DSSE payload: {exc}")

    # Prevent envelope-swap attacks: decoded DSSE payload MUST match the top-level attestation fields
    expected_payload = dict(body)
    expected_payload["attestation_sha256"] = recomputed_sha
    if payload_obj != expected_payload:
        return SignatureVerificationResult(
            False,
            "Ed25519",
            expected_key_id,
            recomputed_sha,
            "DSSE payload mismatch against top-level attestation body (tampering detected).",
        )

    sigs: List[Dict[str, Any]] = env.get("signatures") or []
    if not sigs:
        return SignatureVerificationResult(False, "Ed25519", expected_key_id, recomputed_sha, "Empty signatures list")

    pae = _dsse_pae(pt, payload_bytes)
    last_err = "No matching Ed25519 signature verified."
    for entry in sigs:
        if entry.get("alg") != "Ed25519":
            continue
        try:
            sig_bytes = base64.b64decode(str(entry.get("sig", "")), validate=True)
            pub.verify(sig_bytes, pae)
            return SignatureVerificationResult(
                ok=True,
                algorithm="Ed25519-DSSEv1",
                key_id=str(entry.get("keyid", expected_key_id)),
                attestation_sha256=recomputed_sha,
                reason="PASS",
            )
        except InvalidSignature:
            last_err = "Invalid Ed25519 signature (payload or key mismatch)."
        except Exception as exc:
            last_err = f"Signature decoding error: {exc}"

    return SignatureVerificationResult(False, "Ed25519", expected_key_id, recomputed_sha, last_err)


def sign_attestation_file(
    attestation_path: pathlib.Path,
    private_key_path: pathlib.Path,
    *,
    key_id: Optional[str] = None,
) -> Dict[str, Any]:
    att = json.loads(attestation_path.read_text(encoding="utf-8"))
    signed = sign_attestation_ed25519(att, private_key_path.read_bytes(), key_id=key_id)
    attestation_path.write_text(json.dumps(signed, indent=2) + "\n", encoding="utf-8")
    return signed


def verify_attestation_file(
    attestation_path: pathlib.Path,
    public_key_path: pathlib.Path,
) -> SignatureVerificationResult:
    att = json.loads(attestation_path.read_text(encoding="utf-8"))
    return verify_attestation_signature(att, public_key_path.read_bytes())


def sign_blob_with_cosign(
    attestation_path: pathlib.Path,
    bundle_out: pathlib.Path,
    *,
    key_ref: Optional[str] = None,
) -> Tuple[bool, str]:
    """Optional Sigstore `cosign sign-blob` integration (keyless OIDC in GitHub Actions or local key)."""
    cosign = shutil.which("cosign")
    if not cosign:
        return False, "cosign binary not installed on PATH"
    cmd = [cosign, "sign-blob", "--yes", "--bundle", str(bundle_out)]
    if key_ref:
        cmd.extend(["--key", key_ref])
    cmd.append(str(attestation_path))
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return proc.returncode == 0, out
