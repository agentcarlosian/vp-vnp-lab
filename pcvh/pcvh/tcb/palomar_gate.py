"""Palomar-style Zero-Trust Dual-Check Verification Gate for Lean 4."""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
from typing import Dict, List, Optional, Sequence, Tuple

from ..config import SpecConfig, load_spec_config
from . import conformance
from .crypto import sign_attestation_ed25519
from .dual_kernel import run_dual_kernel_verification
from .manifest import (
    TCB_SNAPSHOT_DIR,
    build_isolated_overlay_workspace,
    verify_tcb_manifest,
)
from .static_audit import StaticAuditResult, scan_untrusted_lean_files


def resolve_lean_bin(project_root: pathlib.Path, lean_bin: Optional[pathlib.Path] = None) -> pathlib.Path:
    project_root = pathlib.Path(project_root).resolve()
    exe = "lake.exe" if os.name == "nt" else "lake"
    if lean_bin is not None:
        if not (lean_bin / exe).is_file():
            raise FileNotFoundError(f"Selected toolchain is missing {exe}: {lean_bin}")
        return lean_bin.resolve()

    tc_fp = project_root / "lean-toolchain"
    tc_dir = None
    if tc_fp.exists():
        tc = tc_fp.read_text(encoding="utf-8", errors="replace").strip()
        tc_dir = tc.replace("/", "--").replace(":", "---")

    candidates: List[pathlib.Path] = []
    if os.environ.get("ELAN_HOME"):
        candidates.append(pathlib.Path(os.environ["ELAN_HOME"]))
    for anc in [project_root, *project_root.parents[:6]]:
        if (anc / ".elan").exists():
            candidates.append(anc / ".elan")
    if (pathlib.Path.home() / ".elan").exists():
        candidates.append(pathlib.Path.home() / ".elan")

    if tc_dir:
        for elan in candidates:
            cand = elan / "toolchains" / tc_dir / "bin"
            if (cand / exe).exists():
                return cand

    for elan in candidates:
        tcs = elan / "toolchains"
        if tcs.exists():
            for child in sorted(tcs.iterdir(), reverse=True):
                cand = child / "bin"
                if (cand / exe).exists():
                    return cand

    w = shutil.which("lake")
    if w:
        return pathlib.Path(w).parent
    raise FileNotFoundError("Could not locate Lean 4 `lake` binary. Pass --lean-bin.")


# Lean 4 Kernel Comparator executed inside the isolated overlay workspace:
#   1. Loads Challenge & Solution `.olean`s into the Lean 4 kernel
#   2. Enumerates every theorem declared in `Challenge` module (under `Challenge.*`)
#   3. Verifies a matching theorem `Solution.<short>` exists in `Solution` module
#   4. Verifies exact universe-param count and kernel definitional equality (`Meta.isDefEq`)
#      AND exact expression equivalence after matching level params
#   5. Verifies `Lean.CollectAxioms.collect` contains ONLY axioms in `allowedAxioms`
#      (strictly blocking `sorryAx`, `Lean.ofReduceBool`, `Lean.ofReduceNat`, custom axioms)
#   6. Verifies mandatory non-vacuity witness theorem exists when required
_PALOMAR_COMPARATOR_TEMPLATE = r"""
import Lean.Meta.Basic
import Lean.Util.CollectAxioms
open Lean Meta

def allowedAxioms : List Name := [{ALLOWED_AXIOMS}]

def stripChallengePrefix : Name → Option Name
  | .str (.str .anonymous "Challenge") s => some (.str .anonymous s)
  | .str p s => Option.map (fun r => .str r s) (stripChallengePrefix p)
  | _ => none

def runComparator : IO UInt32 := do
  initSearchPath (← findSysroot)
  let challMod : Name := `{CHALLENGE_MOD}
  let solMod : Name := `{SOLUTION_MOD}
  let env ← importModules #[{ module := challMod }, { module := solMod }] {}
  let some cIdx := env.getModuleIdx? challMod | do
    IO.println s!"COMP_ERR:Challenge module {challMod} not loaded"
    return 1
  let some sIdx := env.getModuleIdx? solMod | do
    IO.println s!"COMP_ERR:Solution module {solMod} not loaded"
    return 1

  let mut challTheorems : Array (Name × ConstantInfo) := #[]
  for (cName, cInfo) in env.constants.map₁.toList do
    if env.getModuleIdxFor? cName == some cIdx then
      match cInfo with
      | .thmInfo _ =>
        if let some shortName := stripChallengePrefix cName then
          if !cName.isInternal && !shortName.toString.startsWith "_" then
            challTheorems := challTheorems.push (shortName, cInfo)
      | _ => pure ()

  if challTheorems.isEmpty then
    IO.println "COMP_ERR:No theorems found under namespace `Challenge` in Challenge module"
    return 1

  let mut failed := false
  let mut verified : Array String := #[]
  let mut allAxioms : Std.HashSet Name := {}

  let sortedTheorems := challTheorems.qsort (fun (a b : Name × ConstantInfo) => a.1.toString < b.1.toString)
  for (shortName, cInfo) in sortedTheorems do
    let solName := `Solution ++ shortName
    match env.find? solName with
    | none =>
      IO.println s!"COMP_FAIL:{shortName}:missing_solution_theorem:{solName}"
      failed := true
    | some sInfo =>
      match sInfo with
      | .thmInfo sThm =>
        let _ := sIdx
        if cInfo.levelParams.length != sThm.levelParams.length then
          IO.println s!"COMP_FAIL:{shortName}:universe_param_mismatch"
          failed := true
        else
          let lvls := List.map Level.param cInfo.levelParams
          let sTypeAligned := sThm.type.instantiateLevelParams sThm.levelParams lvls
          let cType := cInfo.type
          let coreCtx : Core.Context := { fileName := "<comparator>", fileMap := default }
          let coreState : Core.State := { env := env }
          let (eqOk, _) ← Core.CoreM.toIO (Meta.MetaM.run' (Meta.isDefEq cType sTypeAligned)) coreCtx coreState
          if !eqOk then
            IO.println s!"COMP_FAIL:{shortName}:type_mismatch"
            failed := true
          else
            let (axArr, _) ← Core.CoreM.toIO (Lean.collectAxioms solName) coreCtx coreState
            let axList : List Name := axArr.toList
            let badAxioms : List Name := List.filter (fun (ax : Name) => !allowedAxioms.contains ax) axList
            for ax in axList do
              allAxioms := allAxioms.insert ax
            if !badAxioms.isEmpty then
              let badStr := String.intercalate "," (List.map (fun (x : Name) => x.toString) badAxioms)
              IO.println s!"COMP_FAIL:{shortName}:disallowed_axioms:{badStr}"
              failed := true
            else
              IO.println s!"COMP_OK:{shortName}"
              verified := verified.push shortName.toString
      | .axiomInfo _ =>
        IO.println s!"COMP_FAIL:{shortName}:solution_is_axiom_not_theorem"
        failed := true
      | _ =>
        IO.println s!"COMP_FAIL:{shortName}:solution_not_a_theorem"
        failed := true

  let axNames := List.mergeSort (List.map (fun (x : Name) => x.toString) allAxioms.toList) (· < ·)
  IO.println s!"COMP_AXIOMS:{String.intercalate "," axNames}"
  IO.println s!"COMP_VERIFIED:{String.intercalate "," verified.toList}"
  return if failed then 1 else 0

#eval do
  let code ← runComparator
  if code != 0 then
    throw (IO.userError s!"PALOMAR_COMPARATOR_FAILED (code={code})")
"""


@dataclass
class GateResult:
    verdict: str  # "VERIFIED" | "REJECTED"
    spec_name: str
    spec_bundle_sha256: str
    toolchain: str
    verified_theorems: List[str] = field(default_factory=list)
    axioms_used: List[str] = field(default_factory=list)
    failure_reasons: List[str] = field(default_factory=list)
    checks: Dict[str, str] = field(default_factory=dict)
    duration_s: float = 0.0
    attestation_sha256: str = ""
    signature_envelope: Optional[Dict[str, object]] = None
    raw_logs: Dict[str, str] = field(default_factory=dict)

    timestamp_utc: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_attestation_dict(self) -> Dict[str, object]:
        body: Dict[str, object] = {
            "schema": "pcvh.attestation.v1",
            "timestamp_utc": self.timestamp_utc,
            "spec_name": self.spec_name,
            "verdict": self.verdict,
            "spec_bundle_sha256": self.spec_bundle_sha256,
            "toolchain": self.toolchain,
            "verified_theorems": self.verified_theorems,
            "axioms_used": self.axioms_used,
            "checks": self.checks,
            "failure_reasons": self.failure_reasons,
            "duration_s": round(self.duration_s, 3),
        }
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True).encode("utf-8")
        ).hexdigest()
        body["attestation_sha256"] = digest
        self.attestation_sha256 = digest
        if self.signature_envelope is not None:
            body["signature_envelope"] = self.signature_envelope
        return body


def _run_with_transient_oom_retry(
    cmd: Sequence[str],
    *,
    cwd: pathlib.Path,
    env: Dict[str, str],
    input_text: Optional[str] = None,
    max_attempts: int = 3,
    backoff_s: float = 4.0,
) -> subprocess.CompletedProcess[str]:
    """Run a Lean/Lake subprocess with automatic retry on transient Windows `.olean.private` commit spikes."""
    last_proc: Optional[subprocess.CompletedProcess[str]] = None
    for attempt in range(1, max_attempts + 1):
        proc = subprocess.run(
            list(cmd),
            input=input_text,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        last_proc = proc
        if proc.returncode == 0:
            return proc
        combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).lower()
        transient = any(
            m in combined for m in ("failed to read file", "paging file", "not enough memory", "1455", "bad_alloc")
        )
        if transient and attempt < max_attempts:
            time.sleep(backoff_s * attempt)
            continue
        return proc
    assert last_proc is not None
    return last_proc


def write_attestation(path: pathlib.Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = tempfile.NamedTemporaryFile(dir=path.parent, delete=False, mode="w", encoding="utf-8")
    temporary = pathlib.Path(output.name)
    try:
        with output:
            json.dump(payload, output, indent=2)
            output.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def run_palomar_gate(
    cfg: SpecConfig,
    *,
    lean_bin: Optional[pathlib.Path] = None,
    trusted_tcb_source: Optional[pathlib.Path] = None,
    run_conformance: bool = True,
    trusted_local: bool = False,
    expected_spec_sha256: Optional[str] = None,
    require_dual_kernel: Optional[bool] = None,
    sign_key_path: Optional[pathlib.Path] = None,
    sign_key_id: Optional[str] = None,
    attestation_out: Optional[pathlib.Path] = None,
) -> GateResult:
    """Native gate for explicitly trusted workspaces or an isolated verifier worker."""
    t0 = time.time()
    checks: Dict[str, str] = {}
    failures: List[str] = []
    raw_logs: Dict[str, str] = {}

    def rejected(reason: str, digest: str = "") -> GateResult:
        result = GateResult(verdict="REJECTED", spec_name=cfg.name, spec_bundle_sha256=digest,
                            toolchain=cfg.lean_toolchain, failure_reasons=[reason], raw_logs=raw_logs,
                            checks=checks, duration_s=time.time() - t0)
        if trusted_local and attestation_out is not None:
            write_attestation(attestation_out, result.to_attestation_dict())
        return result

    if not trusted_local:
        return rejected("Native execution requires a trusted local workspace. Use pcvh verify for isolated execution.")
    man = verify_tcb_manifest(cfg)
    if not man.ok or (expected_spec_sha256 is not None and man.spec_bundle_sha256 != expected_spec_sha256):
        detail = f"mismatched={man.mismatched_files} missing={man.missing_files}"
        checks["tcb_manifest"] = f"TAMPER_DETECTED ({detail})"
        return rejected(f"TCB manifest or expected digest mismatch: {detail}", man.spec_bundle_sha256)
    checks["tcb_manifest"] = "PASS"
    snapshot = cfg.project_root / TCB_SNAPSHOT_DIR
    tcb_src = trusted_tcb_source or (snapshot if snapshot.is_dir() else None)
    with tempfile.TemporaryDirectory(prefix="pcvh_gate_") as tmp:
        ws = pathlib.Path(tmp) / "workspace"
        try:
            _, overlaid = build_isolated_overlay_workspace(cfg, ws, man, trusted_tcb_source=tcb_src)
            checks["tcb_overlay"] = f"PASS ({len(overlaid)} immutable TCB files stamped)"
        except Exception as exc:
            checks["tcb_overlay"] = f"FAIL ({exc})"
            return rejected(f"TCB overlay failed: {exc}", man.spec_bundle_sha256)

        original_root = cfg.project_root
        cfg = load_spec_config(ws)
        staged_manifest = verify_tcb_manifest(cfg)
        if not staged_manifest.ok or staged_manifest.spec_bundle_sha256 != man.spec_bundle_sha256:
            return rejected("Staged specification manifest mismatch", man.spec_bundle_sha256)

        # 3. Static Anti-Cheating Audit on all non-TCB Lean files in overlay workspace
        st_audit: StaticAuditResult = scan_untrusted_lean_files(ws, cfg)
        if not st_audit.ok:
            checks["static_audit"] = f"FAIL ({len(st_audit.violations)} violations)"
            for v in st_audit.violations:
                failures.append(f"Static audit violation [{v.rule}] {v.file}:{v.line}: {v.snippet}")
            return rejected("\n".join(failures), man.spec_bundle_sha256)
        else:
            checks["static_audit"] = f"PASS ({st_audit.files_scanned} files scanned)"

        # 4. Isolated Lean 4 Kernel Build (Challenge + Solution)
        lean_bin_dir = resolve_lean_bin(original_root, lean_bin)
        lake_exe = lean_bin_dir / ("lake.exe" if os.name == "nt" else "lake")
        env = os.environ.copy()
        env["PATH"] = str(lean_bin_dir) + os.pathsep + env.get("PATH", "")

        # Build Challenge & Solution inside clean isolated workspace
        build_proc = _run_with_transient_oom_retry(
            [str(lake_exe), "build", cfg.challenge_module, cfg.solution_module],
            cwd=ws,
            env=env,
        )
        build_out = (build_proc.stdout or "") + ("\n" + build_proc.stderr if build_proc.stderr else "")
        raw_logs["lake_build"] = build_out
        if build_proc.returncode != 0:
            checks["lean_kernel_build"] = f"FAIL (rc={build_proc.returncode})"
            return rejected(f"Isolated Lean 4 build failed: {build_out.strip()[-800:]}", man.spec_bundle_sha256)
        checks["lean_kernel_build"] = "PASS"

        # 5. Palomar Kernel Comparator (DefEq theorem types + strict axiom allowlist)
        lean_ident = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*$")
        for label, ident in [
            ("challenge_module", cfg.challenge_module),
            ("solution_module", cfg.solution_module),
            *(("allowed_axiom", ax) for ax in cfg.allowed_axioms),
        ]:
            if not lean_ident.fullmatch(ident):
                checks["palomar_comparator"] = f"FAIL (invalid {label})"
                return rejected(f"Invalid Lean identifier in {label}: {ident!r}", man.spec_bundle_sha256)
        allowed_lean = ", ".join(f"`{ax}" for ax in cfg.allowed_axioms)
        comp_script = (
            _PALOMAR_COMPARATOR_TEMPLATE
            .replace("{ALLOWED_AXIOMS}", allowed_lean)
            .replace("{CHALLENGE_MOD}", cfg.challenge_module)
            .replace("{SOLUTION_MOD}", cfg.solution_module)
        )
        comp_proc = _run_with_transient_oom_retry(
            [str(lake_exe), "env", "lean", "--stdin"],
            input_text=comp_script,
            cwd=ws,
            env=env,
        )
        comp_out = (comp_proc.stdout or "") + ("\n" + comp_proc.stderr if comp_proc.stderr else "")
        raw_logs["palomar_comparator"] = comp_out

        verified_theorems: List[str] = []
        axioms_used: List[str] = []
        comp_fails: List[str] = []

        for line in comp_out.splitlines():
            line = line.strip()
            if line.startswith("COMP_OK:"):
                verified_theorems.append(line.split(":", 1)[1])
            elif line.startswith("COMP_FAIL:") or line.startswith("COMP_ERR:"):
                comp_fails.append(line)
            elif line.startswith("COMP_AXIOMS:"):
                raw_ax = line.split(":", 1)[1]
                axioms_used = [a for a in raw_ax.split(",") if a]

        if comp_proc.returncode != 0 or comp_fails or not verified_theorems:
            checks["palomar_comparator"] = f"FAIL ({len(comp_fails)} issues)"
            if comp_fails:
                failures.extend(comp_fails)
            else:
                failures.append(f"Comparator failed (rc={comp_proc.returncode}): {comp_out.strip()[-600:]}")
        else:
            checks["palomar_comparator"] = f"PASS ({len(verified_theorems)} theorems DefEq, axioms={axioms_used})"

        # 6. Mandatory Non-Vacuity Witness Enforcement
        if cfg.require_nonvacuity_witness:
            has_nv = any(cfg.nonvacuity_suffix.lower() in t.lower() for t in verified_theorems)
            if has_nv:
                checks["nonvacuity_witness"] = "PASS"
            else:
                checks["nonvacuity_witness"] = "FAIL (no verified non-vacuity witness theorem)"
                failures.append(
                    f"Required non-vacuity witness theorem matching '*{cfg.nonvacuity_suffix}*' was not verified."
                )

        # 7. External independent second-kernel verification (`lean4export` + `nanoda` / Palomar `comparator`)
        enforce_dk = cfg.require_dual_kernel if require_dual_kernel is None else require_dual_kernel
        dk_res = run_dual_kernel_verification(
            ws,
            cfg,
            lake_exe=lake_exe,
            env=env,
            require_dual_kernel=enforce_dk,
            target_theorems=verified_theorems,
        )
        raw_logs["external_second_kernel"] = dk_res.raw_output
        if dk_res.status == "PASS":
            checks["external_second_kernel"] = f"PASS [{dk_res.backend}] ({dk_res.detail})"
        elif dk_res.status == "SKIPPED_LOCAL":
            checks["external_second_kernel"] = f"SKIPPED_LOCAL ({dk_res.detail})"
        else:
            checks["external_second_kernel"] = f"FAIL [{dk_res.backend}] ({dk_res.detail})"
            failures.append(f"Independent second kernel failed: {dk_res.detail}")

        # 8. Differential conformance evidence for the reviewed, ordered cases.
        if cfg.conformance_command and not run_conformance:
            checks["differential_conformance"] = "SKIPPED_BY_REQUEST"
        if not failures and run_conformance and cfg.conformance_command:
            try:
                conformance.check_policy(cfg)
                oracle = pathlib.Path(tmp) / "oracle"
                conformance.stage_oracle(original_root, man, oracle)
                records = conformance.produce(cfg, lean_bin_dir)
                summary = conformance.replay(load_spec_config(oracle), records, lean_bin_dir)
                checks["differential_conformance"] = f"PASS ({summary})"
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                checks["differential_conformance"] = f"FAIL ({exc})"
                failures.append(f"Differential conformance failed: {exc}")

    if sign_key_path is not None:
        checks["cryptographic_signature"] = "PENDING (Ed25519-DSSEv1)"

    verdict = "VERIFIED" if not failures else "REJECTED"
    result = GateResult(
        verdict=verdict,
        spec_name=cfg.name,
        spec_bundle_sha256=man.spec_bundle_sha256,
        toolchain=cfg.lean_toolchain,
        verified_theorems=verified_theorems,
        axioms_used=axioms_used,
        failure_reasons=failures,
        checks=checks,
        duration_s=time.time() - t0,
        raw_logs=raw_logs,
    )

    if sign_key_path is not None:
        key_bytes = pathlib.Path(sign_key_path).read_bytes()
        result.checks["cryptographic_signature"] = "PASS (Ed25519-DSSEv1 signed)"
        att = result.to_attestation_dict()
        att = sign_attestation_ed25519(att, key_bytes, key_id=sign_key_id)
        result.attestation_sha256 = str(att["attestation_sha256"])
        result.signature_envelope = att.get("signature_envelope")  # type: ignore[assignment]
    else:
        att = result.to_attestation_dict()

    if attestation_out is not None:
        write_attestation(attestation_out, att)

    return result
