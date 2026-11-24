"""Stage 3 Lemma DAG Planner: decomposes Challenge.lean into isolated minimal-import proof modules."""

from __future__ import annotations

from dataclasses import dataclass, field
import pathlib
import re
from typing import Dict, List, Set

from ..config import SpecConfig
from ..falsify.falsifier import ParsedChallengeTheorem, parse_challenge_file
from ..tcb.static_audit import strip_lean_comments_and_strings


@dataclass
class LemmaTask:
    name: str
    module_name: str              # e.g. Proofs.Lem_step_conserves
    rel_file_path: str            # e.g. Proofs/Lem_step_conserves.lean
    theorem: ParsedChallengeTheorem
    depends_on: List[str] = field(default_factory=list)  # upstream theorem names
    unfold_candidates: List[str] = field(default_factory=list)
    induction_candidates: List[tuple[str, str]] = field(default_factory=list)  # [(var, type)]
    is_nonvacuity: bool = False


@dataclass
class ProofPlan:
    statement_module: str
    open_namespaces: List[str]
    statement_defs: List[str]
    tasks: List[LemmaTask]        # already topologically ordered

    def to_dict(self) -> Dict[str, object]:
        return {
            "statement_module": self.statement_module,
            "open_namespaces": list(self.open_namespaces),
            "statement_defs": list(self.statement_defs),
            "tasks": [
                {
                    "name": t.name,
                    "module_name": t.module_name,
                    "depends_on": list(t.depends_on),
                    "unfold_candidates": list(t.unfold_candidates),
                    "induction_candidates": [list(x) for x in t.induction_candidates],
                    "is_nonvacuity": t.is_nonvacuity,
                }
                for t in self.tasks
            ],
        }


_DEF_NAME_RE = re.compile(
    r"^\s*(?:private\s+|protected\s+|noncomputable\s+)*(?:def|abbrev)\s+([A-Za-z_][A-Za-z0-9_']*)\b",
    re.MULTILINE,
)

_IND_NAME_RE = re.compile(
    r"^\s*inductive\s+([A-Za-z_][A-Za-z0-9_']*)\b",
    re.MULTILINE,
)


def _extract_statement_symbols(stmt_path: pathlib.Path) -> tuple[List[str], Set[str]]:
    raw = stmt_path.read_text(encoding="utf-8", errors="replace")
    cleaned = strip_lean_comments_and_strings(raw)
    defs = list(dict.fromkeys(_DEF_NAME_RE.findall(cleaned)))
    inductives = set(_IND_NAME_RE.findall(cleaned))
    return defs, inductives


def _sanitize_mod_suffix(thm_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", thm_name)


def _extract_statement_call_depths(stmt_path: pathlib.Path, stmt_defs: List[str]) -> Dict[str, int]:
    """Estimate call-graph depth of each definition in Statement.lean (leaf helpers < composite passes)."""
    raw = stmt_path.read_text(encoding="utf-8", errors="replace")
    cleaned = strip_lean_comments_and_strings(raw)
    # Split source into declaration chunks starting at each def/abbrev
    def_spans: Dict[str, str] = {}
    matches = list(_DEF_NAME_RE.finditer(cleaned))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned)
        def_spans[m.group(1)] = cleaned[start:end]

    callees: Dict[str, Set[str]] = {}
    def_set = set(stmt_defs)
    for d in stmt_defs:
        body = def_spans.get(d, "")
        callees[d] = {other for other in def_set if other != d and re.search(rf"\b{re.escape(other)}\b", body)}

    depths: Dict[str, int] = {d: 0 for d in stmt_defs}
    for _ in range(len(stmt_defs) + 1):
        changed = False
        for d in stmt_defs:
            if callees[d]:
                nd = 1 + max(depths[c] for c in callees[d])
                if nd > depths[d]:
                    depths[d] = nd
                    changed = True
        if not changed:
            break
    return depths


def build_proof_plan(cfg: SpecConfig) -> ProofPlan:
    """Analyze `Statement.lean` + `Challenge.lean` and construct a topological Lemma DAG plan."""
    stmt_path = cfg.project_root / cfg.statement_rel
    chall_path = cfg.project_root / cfg.challenge_rel
    stmt_mod = ".".join(pathlib.Path(cfg.statement_rel).with_suffix("").parts)

    stmt_defs, stmt_inductives = _extract_statement_symbols(stmt_path)
    call_depths = _extract_statement_call_depths(stmt_path, stmt_defs)
    theorems = parse_challenge_file(chall_path)
    all_opens: List[str] = []
    for t in theorems:
        for ns in t.open_namespaces:
            if ns not in all_opens:
                all_opens.append(ns)

    prelim: List[LemmaTask] = []
    thm_max_depth: Dict[str, int] = {}
    for thm in theorems:
        is_nv = cfg.nonvacuity_suffix.lower() in thm.name.lower()
        sig_text = thm.raw_signature
        unfolds = [d for d in stmt_defs if re.search(rf"\b{re.escape(d)}\b", sig_text)]
        thm_max_depth[thm.name] = max((call_depths.get(d, 0) for d in unfolds), default=0)

        ind_cands: List[tuple[str, str]] = []
        for vn, ty in thm.binders:
            if ty.startswith("List ") or ty == "Nat" or ty in stmt_inductives:
                ind_cands.append((vn, ty))

        mod_suf = _sanitize_mod_suffix(thm.name)
        prelim.append(
            LemmaTask(
                name=thm.name,
                module_name=f"Solution.Lem_{mod_suf}",
                rel_file_path=f"Solution/Lem_{mod_suf}.lean",
                theorem=thm,
                unfold_candidates=unfolds,
                induction_candidates=ind_cands,
                is_nonvacuity=is_nv,
            )
        )

    def tier_key(t: LemmaTask) -> tuple[int, int, str]:
        if t.is_nonvacuity:
            return (0, 0, t.name)
        return (1, thm_max_depth.get(t.name, 0), t.name)

    ordered = sorted(prelim, key=tier_key)

    # Link higher call-depth theorems to lower call-depth proved theorems so composite passes reuse helper lemmas!
    for t in ordered:
        if t.is_nonvacuity:
            continue
        my_d = thm_max_depth.get(t.name, 0)
        t.depends_on = [
            prev.name
            for prev in ordered
            if not prev.is_nonvacuity and prev.name != t.name and thm_max_depth.get(prev.name, 0) < my_d
        ]

    return ProofPlan(
        statement_module=stmt_mod,
        open_namespaces=all_opens,
        statement_defs=stmt_defs,
        tasks=ordered,
    )


def render_solution_aggregator(plan: ProofPlan, proved_modules: Dict[str, str]) -> str:
    """Generate `Solution.lean` re-exporting every proved theorem into `namespace Solution`."""
    imports = [f"import {plan.statement_module}"]
    for t in plan.tasks:
        if t.name in proved_modules:
            imports.append(f"import {proved_modules[t.name]}")

    opens_line = f"open {' '.join(plan.open_namespaces)}\n" if plan.open_namespaces else ""
    body_lines = [
        "\n".join(imports),
        "",
        "/- Auto-assembled by PCVH Stage 3/4 Orchestrator. Verified by Zone C Palomar Gate. -/",
        "",
        "namespace Solution",
    ]
    if opens_line:
        body_lines.append(opens_line.rstrip())
    body_lines.append("")

    for t in plan.tasks:
        if t.name not in proved_modules:
            continue
        # Re-export exact theorem signature referencing `Proofs.<name>`
        # Binder variable forwarding preserves exact DefEq type!
        binders_only = " ".join(f"({vn} : {ty})" for vn, ty in t.theorem.binders)
        arg_names = " ".join(vn for vn, _ in t.theorem.binders)
        if binders_only:
            decl = f"theorem {t.name} {binders_only} : {t.theorem.body_prop} :=\n  PCVHProofs.{t.name} {arg_names}"
        else:
            decl = f"theorem {t.name} : {t.theorem.body_prop} :=\n  PCVHProofs.{t.name}"
        body_lines.append(decl)
        body_lines.append("")

    body_lines.append("end Solution")
    body_lines.append("")
    return "\n".join(body_lines)
