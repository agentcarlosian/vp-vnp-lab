"""Stage 2 Executable Falsification Pre-Check: refutes false specs in seconds before launching provers."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import pathlib
import random
import re
import subprocess
import time
from typing import Dict, List, Optional, Tuple

from ..config import SpecConfig
from ..tcb.palomar_gate import _run_with_transient_oom_retry, resolve_lean_bin
from ..tcb.static_audit import strip_lean_comments_and_strings


@dataclass
class FalsificationCounterexample:
    theorem: str
    inputs: str
    source: str  # "lean-bounded-eval" | "external-oracle"


@dataclass
class FalsificationResult:
    status: str  # "PASSED" | "REFUTED" | "MISSING_NONVACUITY" | "SKIPPED"
    duration_s: float
    theorems_tested: List[str] = field(default_factory=list)
    samples_evaluated: int = 0
    counterexamples: List[FalsificationCounterexample] = field(default_factory=list)
    external_output: str = ""
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in ("PASSED", "SKIPPED")

    def to_dict(self) -> Dict[str, object]:
        return {
            "status": self.status,
            "duration_s": round(self.duration_s, 3),
            "theorems_tested": list(self.theorems_tested),
            "samples_evaluated": self.samples_evaluated,
            "counterexamples": [
                {"theorem": c.theorem, "inputs": c.inputs, "source": c.source}
                for c in self.counterexamples
            ],
            "notes": list(self.notes),
        }


@dataclass
class ParsedChallengeTheorem:
    name: str
    binders: List[Tuple[str, str]]  # [(var_name, type_str), ...]
    body_prop: str
    raw_signature: str
    open_namespaces: List[str]


_THEOREM_RE = re.compile(
    r"^\s*theorem\s+([A-Za-z_][A-Za-z0-9_']*)\s*([\s\S]*?)\s*:=\s*by\b",
    re.MULTILINE,
)

_OPEN_RE = re.compile(r"^\s*open\s+([A-Za-z0-9_. ]+)", re.MULTILINE)


def _split_binders_and_body(sig_block: str) -> Tuple[List[Tuple[str, str]], str]:
    """Parse Lean binder groups `(x y : Nat) (h : P) : Body` into `(binders, body)`."""
    s = sig_block.strip()
    binders: List[Tuple[str, str]] = []
    i = 0
    n = len(s)

    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break
        if s[i] == ":":
            return binders, s[i + 1 :].strip()
        if s[i] in "({[":
            open_ch = s[i]
            close_ch = {"(": ")", "{": "}", "[": "]"}[open_ch]
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if s[j] == open_ch:
                    depth += 1
                elif s[j] == close_ch:
                    depth -= 1
                j += 1
            inner = s[i + 1 : j - 1].strip()
            if ":" in inner:
                lhs, rhs = inner.split(":", 1)
                var_names = [v for v in lhs.strip().split() if v]
                ty = rhs.strip()
                for vn in var_names:
                    binders.append((vn, ty))
            i = j
        else:
            break

    return binders, s


def parse_challenge_file(challenge_path: pathlib.Path) -> List[ParsedChallengeTheorem]:
    """Extract theorem headers from `Challenge.lean` (preserving exact signatures for falsification & planning)."""
    raw = challenge_path.read_text(encoding="utf-8", errors="replace")
    cleaned = strip_lean_comments_and_strings(raw)
    opens: List[str] = []
    for m in _OPEN_RE.finditer(cleaned):
        for tok in m.group(1).split():
            if tok and tok not in opens and tok != "in":
                opens.append(tok)

    out: List[ParsedChallengeTheorem] = []
    for m in _THEOREM_RE.finditer(cleaned):
        name = m.group(1)
        sig_block = m.group(2).strip()
        binders, body = _split_binders_and_body(sig_block)
        out.append(
            ParsedChallengeTheorem(
                name=name,
                binders=binders,
                body_prop=body,
                raw_signature=f"theorem {name} {sig_block}".strip(),
                open_namespaces=list(opens),
            )
        )
    return out


_SUPPORTED_GEN_TYPES = {"Nat", "Int", "Bool", "List Nat", "List Int"}


def _sample_value(ty: str, rng: random.Random, idx: int) -> str:
    if ty == "Nat":
        edge = [0, 1, 2, 3, 5, 10, 42, 100]
        val = edge[idx] if idx < len(edge) else rng.randint(0, 500)
        return str(val)
    if ty == "Int":
        edge = [0, 1, -1, 2, -2, 10, -10, 100]
        val = edge[idx] if idx < len(edge) else rng.randint(-200, 200)
        return f"({val} : Int)"
    if ty == "Bool":
        return "true" if (idx % 2 == 0) else "false"
    if ty == "List Nat":
        if idx == 0:
            return "([] : List Nat)"
        if idx == 1:
            return "[0]"
        if idx == 2:
            return "[1, 1]"
        k = rng.randint(0, 5)
        elems = [str(rng.randint(0, 30)) for _ in range(k)]
        return f"[{', '.join(elems)}]"
    if ty == "List Int":
        if idx == 0:
            return "([] : List Int)"
        k = rng.randint(0, 5)
        elems = [f"({rng.randint(-30, 30)} : Int)" for _ in range(k)]
        return f"[{', '.join(elems)}]"
    raise ValueError(f"Unsupported generator type: {ty}")


def _is_prop_binder(var_name: str, ty: str) -> bool:
    return ty not in _SUPPORTED_GEN_TYPES and (
        var_name.startswith("h")
        or any(op in ty for op in ("=", "≤", "<", "≥", ">", "∈", "≠", "∧", "∨", "→", "¬"))
    )


def _run_lean_bounded_refuter(
    cfg: SpecConfig,
    theorems: List[ParsedChallengeTheorem],
    lean_bin: Optional[pathlib.Path],
) -> Tuple[List[str], int, List[FalsificationCounterexample], List[str]]:
    """Run executable bounded counterexample search inside Lean 4 against `Statement.lean`."""
    rng = random.Random(20261123)
    lean_bin_dir = resolve_lean_bin(cfg.project_root, lean_bin)
    lake_exe = lean_bin_dir / ("lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = str(lean_bin_dir) + os.pathsep + env.get("PATH", "")

    stmt_mod = ".".join(pathlib.Path(cfg.statement_rel).with_suffix("").parts)
    # Ensure Statement module is compiled first so `lake env lean --stdin` can import it
    _run_with_transient_oom_retry([str(lake_exe), "build", stmt_mod], cwd=cfg.project_root, env=env)

    tested: List[str] = []
    total_samples = 0
    cex_list: List[FalsificationCounterexample] = []
    notes: List[str] = []

    for thm in theorems:
        if cfg.nonvacuity_suffix.lower() in thm.name.lower():
            # Test non-vacuity witness directly if it has 0 binders
            if not thm.binders:
                opens_line = f"open {' '.join(thm.open_namespaces)}\n" if thm.open_namespaces else ""
                script = (
                    f"import {stmt_mod}\n"
                    f"{opens_line}"
                    f"#eval do\n"
                    f"  let ok : Bool := decide ({thm.body_prop})\n"
                    f"  if ok then IO.println \"FALSIFY_OK:1\" else IO.println \"FALSIFY_CEX:{thm.name}:witness_is_false\"\n"
                )
                proc = _run_with_transient_oom_retry(
                    [str(lake_exe), "env", "lean", "--stdin"],
                    input_text=script,
                    cwd=cfg.project_root,
                    env=env,
                )
                out = (proc.stdout or "") + "\n" + (proc.stderr or "")
                if "FALSIFY_CEX:" in out:
                    tested.append(thm.name)
                    total_samples += 1
                    cex_list.append(
                        FalsificationCounterexample(
                            theorem=thm.name,
                            inputs="<non-vacuity witness evaluated to false>",
                            source="lean-bounded-eval",
                        )
                    )
                elif "FALSIFY_OK:" in out:
                    tested.append(thm.name)
                    total_samples += 1
            continue

        # Partition binders into testable value binders and decidable hypothesis preconditions
        val_binders: List[Tuple[str, str]] = []
        hyp_props: List[str] = []
        skip_reason: Optional[str] = None
        for vn, ty in thm.binders:
            if ty in _SUPPORTED_GEN_TYPES:
                val_binders.append((vn, ty))
            elif _is_prop_binder(vn, ty):
                hyp_props.append(ty)
            else:
                skip_reason = f"custom binder type `{ty}`"
                break

        if skip_reason or not val_binders:
            if skip_reason:
                notes.append(f"Skipped built-in generator for `{thm.name}` ({skip_reason}); deferring to external oracle/prover.")
            continue

        # Generate bounded edge + random sample tuples inside a single `for`-loop
        # (synthesizes `Decidable` only ONCE per theorem -> ~10x faster Lean elaboration!)
        n_samples = cfg.falsification_lean_samples
        if len(val_binders) == 1:
            vn0, ty0 = val_binders[0]
            pat = vn0
            tup_ty = ty0
            sample_items = [_sample_value(ty0, rng, s_idx) for s_idx in range(n_samples)]
        else:
            pat = "(" + ", ".join(vn for vn, _ in val_binders) + ")"
            tup_ty = " × ".join(ty for _, ty in val_binders)
            sample_items = [
                "(" + ", ".join(_sample_value(ty, rng, s_idx + vi) for vi, (_, ty) in enumerate(val_binders)) + ")"
                for s_idx in range(n_samples)
            ]

        if hyp_props:
            cond = " ∧ ".join(f"({h})" for h in hyp_props)
            check_expr = f"if decide ({cond}) then decide ({thm.body_prop}) else true"
        else:
            check_expr = f"decide ({thm.body_prop})"

        opens_line = f"open {' '.join(thm.open_namespaces)}\n" if thm.open_namespaces else ""
        script = (
            f"import {stmt_mod}\n"
            f"{opens_line}"
            f"#eval do\n"
            f"  let samples : List ({tup_ty}) := [{', '.join(sample_items)}]\n"
            f"  for {pat} in samples do\n"
            f"    if !({check_expr}) then\n"
            f"      IO.println s!\"FALSIFY_CEX:{thm.name}:{{reprStr {pat}}}\"\n"
            f"      return ()\n"
            f"  IO.println \"FALSIFY_OK:{n_samples}\"\n"
        )
        proc = _run_with_transient_oom_retry(
            [str(lake_exe), "env", "lean", "--stdin"],
            input_text=script,
            cwd=cfg.project_root,
            env=env,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        found_cex = False
        for line in out.splitlines():
            if line.startswith("FALSIFY_CEX:"):
                parts = line.split(":", 2)
                cex_list.append(
                    FalsificationCounterexample(
                        theorem=parts[1],
                        inputs=parts[2] if len(parts) > 2 else "",
                        source="lean-bounded-eval",
                    )
                )
                found_cex = True
                break
        if found_cex:
            tested.append(thm.name)
            total_samples += n_samples
        elif "FALSIFY_OK:" in out:
            tested.append(thm.name)
            total_samples += n_samples
        else:
            notes.append(f"Theorem `{thm.name}` body is not automatically Decidable; skipped bounded #eval.")

    return tested, total_samples, cex_list, notes


def run_falsification_precheck(
    cfg: SpecConfig,
    *,
    lean_bin: Optional[pathlib.Path] = None,
) -> FalsificationResult:
    """Stage 2 Pre-Check: verify non-vacuity declaration exists and try to refute Challenge before proving."""
    t0 = time.time()
    if not cfg.falsification_enabled:
        return FalsificationResult(status="SKIPPED", duration_s=time.time() - t0)

    chall_path = cfg.project_root / cfg.challenge_rel
    theorems = parse_challenge_file(chall_path)
    notes: List[str] = []

    if cfg.require_nonvacuity_witness:
        has_nv = any(cfg.nonvacuity_suffix.lower() in t.name.lower() for t in theorems)
        if not has_nv:
            return FalsificationResult(
                status="MISSING_NONVACUITY",
                duration_s=time.time() - t0,
                notes=[
                    f"Challenge.lean declares no non-vacuity witness theorem matching '*{cfg.nonvacuity_suffix}*'."
                ],
            )

    # 1. Built-in Lean 4 bounded executable refuter
    tested, n_samples, cex_list, lean_notes = _run_lean_bounded_refuter(cfg, theorems, lean_bin)
    notes.extend(lean_notes)

    if cex_list:
        return FalsificationResult(
            status="REFUTED",
            duration_s=time.time() - t0,
            theorems_tested=tested,
            samples_evaluated=n_samples,
            counterexamples=cex_list,
            notes=notes,
        )

    # 2. Optional external falsification oracle (e.g. Hypothesis / Z3 / Foundry)
    ext_out = ""
    if cfg.falsification_command:
        try:
            proc = subprocess.run(
                cfg.falsification_command,
                shell=True,
                cwd=str(cfg.project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=cfg.falsification_max_seconds,
            )
            ext_out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
            if proc.returncode != 0:
                cex_list.append(
                    FalsificationCounterexample(
                        theorem="<external-falsifier>",
                        inputs=ext_out.strip()[-500:],
                        source="external-oracle",
                    )
                )
                return FalsificationResult(
                    status="REFUTED",
                    duration_s=time.time() - t0,
                    theorems_tested=tested,
                    samples_evaluated=n_samples,
                    counterexamples=cex_list,
                    external_output=ext_out,
                    notes=notes,
                )
            notes.append(f"External falsification oracle passed ({cfg.falsification_command}).")
        except subprocess.TimeoutExpired:
            notes.append(f"External falsifier reached max_seconds={cfg.falsification_max_seconds} with no counterexample.")

    return FalsificationResult(
        status="PASSED",
        duration_s=time.time() - t0,
        theorems_tested=tested,
        samples_evaluated=n_samples,
        counterexamples=[],
        external_output=ext_out,
        notes=notes,
    )
