"""Best-First Proof-Tree Search with Live Lean 4 LSP Goal-State Backtracking."""

from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import pathlib
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..config import SpecConfig
from ..runtime.lean_diagnostics import LeanLSPClient, check_lean_file_json
from ..tcb.static_audit import BANNED_RULES, strip_lean_comments_and_strings
from .planner import LemmaTask, ProofPlan
from .retriever import PremiseIndex


@dataclass
class TreeSearchConfig:
    max_expansions: int = 24
    max_depth: int = 5
    max_seconds: float = 45.0
    branch_factor: int = 4
    llm_branch_k: int = 3


@dataclass
class TreeSearchResult:
    proved: bool
    tactic_steps: List[str] = field(default_factory=list)
    nodes_expanded: int = 0
    nodes_enqueued: int = 0
    backtracks: int = 0
    pruned_duplicates: int = 0
    max_depth_reached: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    goal_trace: List[Dict[str, object]] = field(default_factory=list)
    last_errors: List[str] = field(default_factory=list)

    @property
    def tactic_body(self) -> str:
        return "\n".join(self.tactic_steps)

    def to_dict(self) -> Dict[str, object]:
        return {
            "proved": self.proved,
            "tactic_steps": list(self.tactic_steps),
            "nodes_expanded": self.nodes_expanded,
            "nodes_enqueued": self.nodes_enqueued,
            "backtracks": self.backtracks,
            "pruned_duplicates": self.pruned_duplicates,
            "max_depth_reached": self.max_depth_reached,
            "cost_usd": round(self.cost_usd, 4),
            "duration_s": round(self.duration_s, 3),
        }


def _has_banned(tactic: str) -> bool:
    cleaned = strip_lean_comments_and_strings(tactic)
    return any(pat.search(cleaned) for _, pat in BANNED_RULES)


def _canonical_goal_key(goals: Sequence[str]) -> Tuple[str, ...]:
    return tuple(re.sub(r"\s+", " ", g.strip()) for g in goals)


def _goal_score(goals: Sequence[str], depth: int, prior_bonus: float = 0.0) -> Tuple[int, float, int]:
    """Lower tuple = higher priority in best-first heap."""
    n_goals = len(goals)
    char_len = sum(len(g) for g in goals) / max(n_goals, 1) if n_goals else 0.0
    return (n_goals, round(char_len - prior_bonus * 10.0, 2), depth)


def _extract_target_after_turnstile(goal: str) -> str:
    if "⊢" in goal:
        return goal.split("⊢", 1)[1].strip()
    return goal.strip()


def _render_prefix_module(
    plan: ProofPlan,
    task: LemmaTask,
    dep_modules: Sequence[str],
    tactic_steps: Sequence[str],
    *,
    append_sorry: bool,
) -> Tuple[str, int]:
    """Render candidate lemma file and return `(content, probe_line_0idx)`."""
    imports = [f"import {plan.statement_module}"]
    for dm in dep_modules:
        if dm not in imports:
            imports.append(f"import {dm}")

    lines: List[str] = list(imports)
    lines.append("")
    lines.append("namespace PCVHProofs")
    if plan.open_namespaces:
        lines.append(f"open {' '.join(plan.open_namespaces)}")
    lines.append("")

    binders_only = " ".join(f"({vn} : {ty})" for vn, ty in task.theorem.binders)
    if binders_only:
        lines.append(f"theorem {task.name} {binders_only} : {task.theorem.body_prop} := by")
    else:
        lines.append(f"theorem {task.name} : {task.theorem.body_prop} := by")

    for step in tactic_steps:
        for sub in step.splitlines():
            if sub.strip():
                lines.append("  " + sub.rstrip())

    probe_line = len(lines)
    if append_sorry:
        lines.append("  sorry")

    lines.append("")
    lines.append("end PCVHProofs")
    lines.append("")
    return "\n".join(lines), probe_line


def _generate_goal_directed_steps(
    plan: ProofPlan,
    task: LemmaTask,
    upstream_names: Sequence[str],
    goals: Sequence[str],
    prefix: Sequence[str],
) -> List[Tuple[str, float]]:
    """Generate goal-directed single-step Lean 4 tactics with heuristic priors."""
    if not goals:
        return []
    first_goal = goals[0]
    target = _extract_target_after_turnstile(first_goal)
    all_defs = list(plan.statement_defs)
    unfolds = [d for d in task.unfold_candidates if re.search(rf"\b{re.escape(d)}\b", target)] or task.unfold_candidates
    up_simp = [f"PCVHProofs.{u}" for u in upstream_names]
    combined = ", ".join(all_defs + up_simp)
    unfold_csv = ", ".join(unfolds) if unfolds else ", ".join(all_defs)

    steps: List[Tuple[str, float]] = []

    # 1. Direct closers (highest priority if goal is small/arithmetic/boolean)
    steps.extend([
        ("omega", 3.0),
        ("rfl", 2.8),
        ("decide", 2.6),
        ("grind", 2.5),
    ])
    if combined:
        steps.append((f"simp [{combined}]", 2.7))

    # 2. Structural introduction / decomposition based on goal head syntax
    if target.startswith("∀") or "→" in target:
        steps.append(("intro", 2.4))
    if "∧" in target:
        steps.append(("constructor", 2.4))
    if "↔" in target:
        steps.append(("constructor", 2.3))
    if "if " in target or "match " in target:
        steps.append(("split", 2.9))
        steps.append(("all_goals (try split)", 2.2))

    # 3. Unfolding definitions that actually appear in the active goal
    if unfold_csv and not any("simp only" in p or "unfold " in p for p in prefix):
        steps.append((f"simp only [{unfold_csv}]", 2.6))
        steps.append((f"unfold {' '.join(unfolds or all_defs)}", 2.1))
    if combined:
        steps.append((f"all_goals (try simp_all [{combined}])", 2.0))
        steps.append(("all_goals (try omega)", 1.9))
        steps.append(("all_goals (try grind)", 1.8))

    # 4. Structural cases / induction on binders if not already split
    for var_name, var_ty in task.induction_candidates:
        if not any(f"induction {var_name}" in p or f"cases {var_name}" in p for p in prefix):
            steps.append((f"cases {var_name}", 1.7))
            steps.append((f"induction {var_name}", 1.6))

    # Deduplicate and avoid repeating the exact last step
    seen: Set[str] = set()
    out: List[Tuple[str, float]] = []
    last = prefix[-1] if prefix else None
    for s, prio in steps:
        if s not in seen and s != last and not _has_banned(s):
            seen.add(s)
            out.append((s, prio))
    return out


class BestFirstProofSearch:
    """Best-first proof-tree search driven by live Lean 4 LSP (`$/lean/plainGoal`) + backtracking."""

    def __init__(
        self,
        cfg: SpecConfig,
        plan: ProofPlan,
        premise_index: PremiseIndex,
        *,
        lean_bin: Optional[pathlib.Path] = None,
        llm_backend: Optional[Any] = None,
        search_config: Optional[TreeSearchConfig] = None,
    ) -> None:
        self.cfg = cfg
        self.plan = plan
        self.premise_index = premise_index
        self.lean_bin = lean_bin
        self.llm_backend = llm_backend
        self.scfg = search_config or TreeSearchConfig()

    def search(
        self,
        task: LemmaTask,
        dep_modules: Sequence[str],
        upstream_names: Sequence[str],
        target_fp: pathlib.Path,
        *,
        budget_remaining_usd: float = 5.0,
    ) -> TreeSearchResult:
        t0 = time.time()
        target_fp.parent.mkdir(parents=True, exist_ok=True)
        cost_spent = 0.0
        nodes_expanded = 0
        nodes_enqueued = 0
        backtracks = 0
        pruned_dups = 0
        max_depth = 0
        goal_trace: List[Dict[str, object]] = []
        last_errors: List[str] = []

        stub_src, probe_line = _render_prefix_module(self.plan, task, dep_modules, [], append_sorry=True)
        target_fp.write_text(stub_src, encoding="utf-8")

        with LeanLSPClient(self.cfg.project_root, lean_bin=self.lean_bin) as lsp:
            _, root_goals, _ = lsp.evaluate_state(target_fp, stub_src, probe_line, 2, timeout=20.0)
            if not root_goals:
                root_goals = [f"⊢ {task.theorem.body_prop}"]

            visited: Set[Tuple[str, ...]] = {_canonical_goal_key(root_goals)}
            # Heap item: (score_tuple, tie_id, depth, tactic_prefix, active_goals)
            counter = 0
            heap: List[Tuple[Tuple[int, float, int], int, int, List[str], List[str]]] = []
            heapq.heappush(heap, (_goal_score(root_goals, 0), counter, 0, [], list(root_goals)))
            nodes_enqueued += 1

            while heap and nodes_expanded < self.scfg.max_expansions:
                if (time.time() - t0) > self.scfg.max_seconds:
                    break
                _, _, depth, prefix, goals = heapq.heappop(heap)
                nodes_expanded += 1
                max_depth = max(max_depth, depth)
                goal_trace.append({"depth": depth, "prefix": list(prefix), "goals": list(goals[:3])})

                if depth >= self.scfg.max_depth:
                    backtracks += 1
                    continue

                # Gather candidate next tactic steps (LLM policy first if wired, then goal-directed symbolic)
                step_cands: List[Tuple[str, float]] = []
                if (
                    self.llm_backend is not None
                    and hasattr(self.llm_backend, "propose_tactic_steps")
                    and cost_spent < budget_remaining_usd
                ):
                    try:
                        q_text = "\n".join(goals)
                        prem_txt = self.premise_index.format_for_prompt(q_text, top_k=6)
                        llm_steps, step_cost = self.llm_backend.propose_tactic_steps(
                            task.theorem.raw_signature,
                            prefix,
                            goals,
                            prem_txt,
                            k=self.scfg.llm_branch_k,
                        )
                        cost_spent += float(step_cost)
                        for idx, st in enumerate(llm_steps):
                            if st and not _has_banned(st):
                                step_cands.append((st, 4.0 - idx * 0.2))
                    except Exception as exc:
                        last_errors.append(f"LLM step proposal error: {exc}")

                step_cands.extend(
                    _generate_goal_directed_steps(self.plan, task, upstream_names, goals, prefix)
                )

                # Deduplicate preserving highest priority
                seen_s: Set[str] = set()
                ordered_steps: List[Tuple[str, float]] = []
                for s, p in step_cands:
                    if s not in seen_s:
                        seen_s.add(s)
                        ordered_steps.append((s, p))

                children_pushed = 0
                for step_tac, prio in ordered_steps:
                    if (time.time() - t0) > self.scfg.max_seconds:
                        break
                    cand_prefix = [*prefix, step_tac]

                    # 1. Test candidate with trailing `sorry` via fast incremental `didChange` LSP!
                    probe_src, p_line = _render_prefix_module(
                        self.plan, task, dep_modules, cand_prefix, append_sorry=True
                    )
                    diags, next_goals, _ = lsp.evaluate_state(target_fp, probe_src, p_line, 2, timeout=12.0)

                    # Ignore the warning about `declaration uses 'sorry'`; check ONLY real errors!
                    errs = [d for d in diags if d.severity == "error"]
                    # Special case: if Lean reports "no goals to be solved" on the trailing `sorry`,
                    # that means `cand_prefix` ALREADY CLOSED ALL GOALS!
                    closed_on_sorry = any(
                        "no goals to be solved" in d.message.lower()
                        for d in errs
                    )
                    other_errs = [
                        d for d in errs
                        if "no goals to be solved" not in d.message.lower()
                    ]

                    if not other_errs and (closed_on_sorry or not next_goals):
                        # Verify clean proof WITHOUT `sorry` via authoritative `lean --json`!
                        clean_src, _ = _render_prefix_module(
                            self.plan, task, dep_modules, cand_prefix, append_sorry=False
                        )
                        target_fp.write_text(clean_src, encoding="utf-8")
                        chk = check_lean_file_json(self.cfg.project_root, target_fp, lean_bin=self.lean_bin)
                        if chk.ok:
                            return TreeSearchResult(
                                proved=True,
                                tactic_steps=cand_prefix,
                                nodes_expanded=nodes_expanded,
                                nodes_enqueued=nodes_enqueued,
                                backtracks=backtracks,
                                pruned_duplicates=pruned_dups,
                                max_depth_reached=max(max_depth, depth + 1),
                                cost_usd=cost_spent,
                                duration_s=time.time() - t0,
                                goal_trace=goal_trace,
                            )
                        # If clean check still had unsolved goals (e.g. a sibling goal), fall through cleanly!
                        last_errors = [d.format_compact() for d in chk.errors]
                        backtracks += 1
                        continue

                    if other_errs:
                        last_errors = [d.format_compact() for d in other_errs[:3]]
                        backtracks += 1
                        continue

                    # Valid intermediate tactic state! Deduplicate canonical goals before pushing
                    g_key = _canonical_goal_key(next_goals)
                    if g_key in visited:
                        pruned_dups += 1
                        continue
                    visited.add(g_key)

                    counter += 1
                    score = _goal_score(next_goals, depth + 1, prior_bonus=prio)
                    heapq.heappush(heap, (score, counter, depth + 1, cand_prefix, next_goals))
                    nodes_enqueued += 1
                    children_pushed += 1
                    if children_pushed >= self.scfg.branch_factor:
                        break

                if children_pushed == 0:
                    backtracks += 1

        return TreeSearchResult(
            proved=False,
            nodes_expanded=nodes_expanded,
            nodes_enqueued=nodes_enqueued,
            backtracks=backtracks,
            pruned_duplicates=pruned_dups,
            max_depth_reached=max_depth,
            cost_usd=cost_spent,
            duration_s=time.time() - t0,
            goal_trace=goal_trace,
            last_errors=last_errors,
        )
