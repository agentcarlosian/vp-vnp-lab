"""Stage 4 Iterative Prover Worker: deterministic tactic escalation + LSP goals + BM25 + pluggable LLM repair."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import pathlib
import re
import time
import urllib.request
from typing import Dict, List, Optional, Protocol, Sequence, Tuple

from ..config import SpecConfig
from ..runtime.lean_diagnostics import LeanLSPClient, check_lean_file_json
from ..tcb.static_audit import BANNED_RULES, strip_lean_comments_and_strings
from .planner import LemmaTask, ProofPlan
from .retriever import PremiseIndex


@dataclass
class ProofPromptContext:
    theorem_name: str
    theorem_signature: str
    module_header: str
    round_idx: int
    live_lsp_goals: List[str]
    retrieved_premises_text: str
    previous_attempt: Optional[str] = None
    previous_errors: List[str] = field(default_factory=list)


class LLMBackend(Protocol):
    """Pluggable LLM backend interface for Tier-3 interactive tactic repair."""

    def propose_tactic_proof(self, ctx: ProofPromptContext) -> Tuple[str, float]:
        """Return `(tactic_body_without_leading_by, estimated_cost_usd)`."""
        ...


class OpenAICompatibleLLMBackend:
    """Zero-dependency OpenAI/Anthropic-compatible HTTP chat-completions prover backend."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1/chat/completions",
        model: str = "gpt-4.1-mini",
        usd_per_call_estimate: float = 0.02,
    ) -> None:
        self.api_key = api_key or os.environ.get("PCVH_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.base_url = base_url
        self.model = model
        self.usd_per_call_estimate = usd_per_call_estimate

    def propose_tactic_proof(self, ctx: ProofPromptContext) -> Tuple[str, float]:
        if not self.api_key:
            raise RuntimeError("No API key configured for OpenAICompatibleLLMBackend.")
        system_msg = (
            "You are a Lean 4 theorem prover. Output ONLY valid Lean 4 tactic lines (no markdown fences, "
            "no `by`, no `sorry`, no `admit`, no `axiom`, no `native_decide`)."
        )
        user_parts = [
            f"Target theorem:\n{ctx.theorem_signature} := by",
            f"Current Lean 4 infoview goals:\n" + ("\n".join(ctx.live_lsp_goals) or "(none)"),
            f"Relevant verified premises:\n{ctx.retrieved_premises_text}",
        ]
        if ctx.previous_attempt:
            user_parts.append(f"Previous failed attempt:\n{ctx.previous_attempt}")
        if ctx.previous_errors:
            user_parts.append("Lean 4 errors:\n" + "\n".join(ctx.previous_errors[:5]))
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": "\n\n".join(user_parts)},
            ],
        }
        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = str(data["choices"][0]["message"]["content"]).strip()
        # Strip accidental markdown fences
        content = re.sub(r"^```(?:lean4?)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        if content.startswith("by\n"):
            content = content[3:]
        return content.strip(), self.usd_per_call_estimate


@dataclass
class TaskProofResult:
    theorem_name: str
    module_name: str
    file_path: pathlib.Path
    proved: bool
    tier_used: str            # "tier0" | "tier1" | "tier2" | "tier3-llm" | "failed"
    attempts: int
    llm_rounds: int
    cost_usd: float
    duration_s: float
    tactic_body: str = ""
    last_errors: List[str] = field(default_factory=list)
    lsp_goals_inspected: List[str] = field(default_factory=list)
    retrieved_premises: List[str] = field(default_factory=list)


def _contains_banned_construct(tactic_body: str) -> Optional[str]:
    cleaned = strip_lean_comments_and_strings(tactic_body)
    for rule_name, pat in BANNED_RULES:
        if pat.search(cleaned):
            return rule_name
    return None


def _indent_tactics(body: str) -> str:
    lines = [ln.rstrip() for ln in body.strip().splitlines() if ln.strip()]
    return "\n".join("  " + ln for ln in lines)


def _render_lemma_module(
    plan: ProofPlan,
    task: LemmaTask,
    dep_modules: Sequence[str],
    tactic_body: str,
) -> Tuple[str, int]:
    """Render isolated Lean file `Solution/Lem_<name>.lean` and return `(content, tactic_start_line_0idx)`."""
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

    tactic_line_0idx = len(lines)
    lines.append(_indent_tactics(tactic_body))
    lines.append("")
    lines.append("end PCVHProofs")
    lines.append("")
    return "\n".join(lines), tactic_line_0idx


def _build_symbolic_candidates(
    plan: ProofPlan,
    task: LemmaTask,
    upstream_theorem_names: Sequence[str],
) -> List[Tuple[str, str]]:
    """Build deterministic Tier-0, Tier-1, Tier-2 tactic scripts tailored to the theorem structure."""
    cands: List[Tuple[str, str]] = []
    unfolds = task.unfold_candidates
    all_defs = plan.statement_defs
    defs_simp = ", ".join(all_defs)
    unfold_str = " ".join(unfolds) if unfolds else " ".join(all_defs)
    up_simp = ", ".join(f"PCVHProofs.{u}" for u in upstream_theorem_names)
    combined_simp = ", ".join(x for x in (defs_simp, up_simp) if x)

    # --- Tier 0: Fast kernel & decision closers ---
    cands.extend([
        ("tier0", "rfl"),
        ("tier0", "decide"),
        ("tier0", "omega"),
        ("tier0", "simp"),
        ("tier0", "grind"),
    ])

    # --- Tier 1: Targeted unfold + simp + nested split + omega / decide / grind ---
    if unfold_str:
        cands.extend([
            ("tier1", f"unfold {unfold_str}; decide"),
            ("tier1", f"unfold {unfold_str}; omega"),
            ("tier1", f"simp [{combined_simp}]"),
            ("tier1", f"simp [{combined_simp}]\nall_goals (try omega)\nall_goals (try grind)"),
            (
                "tier1",
                f"simp only [{combined_simp}]\n"
                f"all_goals (try split)\n"
                f"all_goals (try simp_all [{combined_simp}])\n"
                f"all_goals (try split)\n"
                f"all_goals (try simp_all [{combined_simp}])\n"
                f"all_goals (try omega)\n"
                f"all_goals (try grind)",
            ),
            ("tier1", f"repeat (first | constructor | (simp [{combined_simp}]; done) | decide | omega | grind)"),
        ])

    # --- Tier 2: Structural induction & case splitting over inductive/List/Nat binders ---
    for ind_var, ind_ty in task.induction_candidates:
        other_vals = [
            vn for vn, ty in task.theorem.binders
            if vn != ind_var and not (vn.startswith("h") or any(op in ty for op in ("=", "≤", "<", "∧", "→")))
        ]
        gen_clause = f" generalizing {' '.join(other_vals)}" if other_vals else ""

        if ind_ty.startswith("List "):
            cands.extend([
                (
                    "tier2",
                    f"induction {ind_var}{gen_clause} with\n"
                    f"| nil => simp [{combined_simp}] <;> try omega <;> try grind\n"
                    f"| cons hd tl ih => simp [{combined_simp}, ih] <;> try omega <;> try grind",
                ),
                (
                    "tier2",
                    f"induction {ind_var}{gen_clause} with\n"
                    f"| nil => simp [{combined_simp}]\n"
                    f"| cons hd tl ih =>\n"
                    f"  simp only [{combined_simp}]\n"
                    f"  all_goals (try split)\n"
                    f"  all_goals (try simp_all [{combined_simp}, ih])\n"
                    f"  all_goals (try omega)\n"
                    f"  all_goals (try grind)",
                ),
            ])
        else:
            # Custom inductive AST (e.g. Expr in compiler pass) or Nat induction
            # 1. Clean induction reusing upstream proved helper theorems first (fast!)
            if up_simp:
                cands.append((
                    "tier2",
                    f"induction {ind_var}{gen_clause}\n"
                    f"all_goals (try simp [{unfold_str.replace(' ', ', ')}, {up_simp}, *])\n"
                    f"all_goals (try omega)\n"
                    f"all_goals (try grind)",
                ))
            # 2. General induction + nested split over match/if branches
            cands.extend([
                (
                    "tier2",
                    f"induction {ind_var}{gen_clause}\n"
                    f"all_goals (try simp only [{combined_simp}])\n"
                    f"all_goals (try split)\n"
                    f"all_goals (try simp_all [{defs_simp}])\n"
                    f"all_goals (try split)\n"
                    f"all_goals (try simp_all [{defs_simp}])\n"
                    f"all_goals (try omega)\n"
                    f"all_goals (try grind)",
                ),
                (
                    "tier2",
                    f"cases {ind_var}\n"
                    f"all_goals (try simp_all [{combined_simp}])\n"
                    f"all_goals (try omega)\n"
                    f"all_goals (try grind)",
                ),
            ])

    # Deduplicate preserving order
    seen = set()
    unique: List[Tuple[str, str]] = []
    for tier, body in cands:
        if body not in seen:
            seen.add(body)
            unique.append((tier, body))
    return unique


class IterativeProverWorker:
    """Synthesizes and iteratively repairs proofs for individual LemmaTasks in a ProofPlan."""

    def __init__(
        self,
        cfg: SpecConfig,
        plan: ProofPlan,
        premise_index: PremiseIndex,
        *,
        lean_bin: Optional[pathlib.Path] = None,
        llm_backend: Optional[LLMBackend] = None,
        skip_symbolic_tiers: bool = False,
    ) -> None:
        self.cfg = cfg
        self.plan = plan
        self.premise_index = premise_index
        self.lean_bin = lean_bin
        self.llm_backend = llm_backend
        self.skip_symbolic_tiers = skip_symbolic_tiers
        self.spent_usd = 0.0

    def prove_task(
        self,
        task: LemmaTask,
        proved_modules: Dict[str, str],
    ) -> TaskProofResult:
        t0 = time.time()
        dep_mods = [proved_modules[d] for d in task.depends_on if d in proved_modules]
        upstream_names = [d for d in task.depends_on if d in proved_modules]
        target_fp = self.cfg.project_root / task.rel_file_path
        target_fp.parent.mkdir(parents=True, exist_ok=True)

        attempts = 0
        last_errors: List[str] = []

        # --- Tiers 0, 1, 2: Deterministic symbolic escalation ---
        if not self.skip_symbolic_tiers:
            candidates = _build_symbolic_candidates(self.plan, task, upstream_names)
            for tier, body in candidates:
                attempts += 1
                src, _ = _render_lemma_module(self.plan, task, dep_mods, body)
                target_fp.write_text(src, encoding="utf-8")
                chk = check_lean_file_json(self.cfg.project_root, target_fp, lean_bin=self.lean_bin)
                if chk.ok:
                    return TaskProofResult(
                        theorem_name=task.name,
                        module_name=task.module_name,
                        file_path=target_fp,
                        proved=True,
                        tier_used=tier,
                        attempts=attempts,
                        llm_rounds=0,
                        cost_usd=0.0,
                        duration_s=time.time() - t0,
                        tactic_body=body,
                    )
                last_errors = [d.format_compact() for d in chk.errors]

        # --- Tier 3: Live LSP Goal Extraction + BM25 Premise Retrieval + Iterative LLM Repair ---
        lsp_goals: List[str] = []
        retrieved_names: List[str] = []
        llm_rounds = 0
        task_cost = 0.0

        if self.llm_backend is not None and self.spent_usd < self.cfg.max_token_budget_usd:
            # 1. Extract live infoview goal at `sorry` via Lean 4 headless LSP
            stub_src, tac_line = _render_lemma_module(self.plan, task, dep_mods, "sorry")
            target_fp.write_text(stub_src, encoding="utf-8")
            try:
                with LeanLSPClient(self.cfg.project_root, lean_bin=self.lean_bin) as lsp:
                    lsp_goals, _ = lsp.get_plain_goal(target_fp, line_0idx=tac_line, col_0idx=2, text=stub_src)
            except Exception:
                lsp_goals = [f"⊢ {task.theorem.body_prop}"]

            query_text = "\n".join(lsp_goals) if lsp_goals else task.theorem.raw_signature
            hits = self.premise_index.search(query_text, top_k=8)
            retrieved_names = [h.entry.name for h in hits]
            premises_text = self.premise_index.format_for_prompt(query_text, top_k=8)

            prev_attempt: Optional[str] = None
            prev_errs: List[str] = list(last_errors)
            header_lines = stub_src.splitlines()[:tac_line]

            for r in range(1, self.cfg.max_rounds_per_lemma + 1):
                if self.spent_usd >= self.cfg.max_token_budget_usd:
                    break
                llm_rounds += 1
                attempts += 1
                ctx = ProofPromptContext(
                    theorem_name=task.name,
                    theorem_signature=task.theorem.raw_signature,
                    module_header="\n".join(header_lines),
                    round_idx=r,
                    live_lsp_goals=lsp_goals,
                    retrieved_premises_text=premises_text,
                    previous_attempt=prev_attempt,
                    previous_errors=prev_errs,
                )
                cand_body, cost = self.llm_backend.propose_tactic_proof(ctx)
                self.spent_usd += cost
                task_cost += cost
                prev_attempt = cand_body

                banned = _contains_banned_construct(cand_body)
                if banned:
                    prev_errs = [f"Rejected candidate: contains forbidden construct `{banned}`."]
                    last_errors = prev_errs
                    continue

                src, _ = _render_lemma_module(self.plan, task, dep_mods, cand_body)
                target_fp.write_text(src, encoding="utf-8")
                chk = check_lean_file_json(self.cfg.project_root, target_fp, lean_bin=self.lean_bin)
                if chk.ok:
                    return TaskProofResult(
                        theorem_name=task.name,
                        module_name=task.module_name,
                        file_path=target_fp,
                        proved=True,
                        tier_used="tier3-llm",
                        attempts=attempts,
                        llm_rounds=llm_rounds,
                        cost_usd=task_cost,
                        duration_s=time.time() - t0,
                        tactic_body=cand_body,
                        lsp_goals_inspected=lsp_goals,
                        retrieved_premises=retrieved_names,
                    )
                prev_errs = [d.format_compact() for d in chk.errors] or [chk.raw_output[-400:]]
                last_errors = prev_errs

        return TaskProofResult(
            theorem_name=task.name,
            module_name=task.module_name,
            file_path=target_fp,
            proved=False,
            tier_used="failed",
            attempts=attempts,
            llm_rounds=llm_rounds,
            cost_usd=task_cost,
            duration_s=time.time() - t0,
            last_errors=last_errors,
            lsp_goals_inspected=lsp_goals,
            retrieved_premises=retrieved_names,
        )
