"""BM25 + Type-Signature Premise Retriever backed by Lean 4 `.olean` environment reflection."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import os
import pathlib
import re
from typing import Dict, List, Optional, Sequence

from ..tcb.palomar_gate import _run_with_transient_oom_retry, resolve_lean_bin

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_']*|[≤≥≠=<>+\-*∧∨→↔∀∃∈]")


def tokenize_lean(text: str) -> List[str]:
    """Tokenize Lean identifiers (splitting dotted/camelCase names) and mathematical operators."""
    raw = _TOKEN_RE.findall(text)
    out: List[str] = []
    for tok in raw:
        out.append(tok.lower())
        # Split camelCase / snake_case identifiers for better recall
        for part in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", tok):
            pl = part.lower()
            if pl != tok.lower() and len(pl) >= 2:
                out.append(pl)
    return out


@dataclass(frozen=True)
class PremiseEntry:
    name: str
    short_name: str
    kind: str         # "theorem" | "def" | "inductive"
    signature: str
    module: str


@dataclass(frozen=True)
class RetrievedPremise:
    entry: PremiseEntry
    score: float


class PremiseIndex:
    """Zero-dependency BM25 + exact-symbol overlap index over real Lean 4 declarations."""

    def __init__(self, entries: Sequence[PremiseEntry] = (), k1: float = 1.4, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._entries: List[PremiseEntry] = []
        self._doc_tfs: List[Counter[str]] = []
        self._doc_lens: List[int] = []
        self._df: Counter[str] = Counter()
        self._by_name: Dict[str, int] = {}
        for e in entries:
            self.add(e)

    def __len__(self) -> int:
        return len(self._entries)

    def add(self, entry: PremiseEntry) -> None:
        if entry.name in self._by_name:
            return
        toks = tokenize_lean(f"{entry.name} {entry.short_name} {entry.signature}")
        tf = Counter(toks)
        idx = len(self._entries)
        self._by_name[entry.name] = idx
        self._entries.append(entry)
        self._doc_tfs.append(tf)
        self._doc_lens.append(len(toks))
        for term in tf:
            self._df[term] += 1

    def search(self, query_goal: str, top_k: int = 8) -> List[RetrievedPremise]:
        if not self._entries:
            return []
        q_toks = tokenize_lean(query_goal)
        if not q_toks:
            return []
        n_docs = len(self._entries)
        avgdl = sum(self._doc_lens) / max(1, n_docs)

        scored: List[RetrievedPremise] = []
        for idx, entry in enumerate(self._entries):
            tf = self._doc_tfs[idx]
            dl = self._doc_lens[idx]
            score = 0.0
            for term in set(q_toks):
                f = tf.get(term, 0)
                if f == 0:
                    continue
                df = self._df.get(term, 0)
                idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
                denom = f + self.k1 * (1.0 - self.b + self.b * dl / max(1.0, avgdl))
                score += idf * (f * (self.k1 + 1.0)) / denom
            # Boost theorems slightly over raw defs when retrieving proof lemmas
            if score > 0 and entry.kind == "theorem":
                score *= 1.15
            if score > 0:
                scored.append(RetrievedPremise(entry=entry, score=score))

        scored.sort(key=lambda r: (-r.score, r.entry.name))
        return scored[:top_k]

    def format_for_prompt(self, query_goal: str, top_k: int = 8) -> str:
        hits = self.search(query_goal, top_k=top_k)
        if not hits:
            return "(no matching premises indexed)"
        lines = []
        for h in hits:
            e = h.entry
            lines.append(f"- [{e.kind}] {e.name} : {e.signature}  (from {e.module})")
        return "\n".join(lines)


_REFLECT_PREMISES_TEMPLATE = r"""
import Lean.Meta.Basic
open Lean Meta

def reflectModules : IO Unit := do
  initSearchPath (← findSysroot)
  let mods : List Name := [{MODS}]
  let imports := (List.map (fun (m : Name) => ({ module := m } : Import)) mods).toArray
  let env ← importModules imports {}
  let coreCtx : Core.Context := { fileName := "<retriever>", fileMap := default }
  let coreState : Core.State := { env := env }
  for modName in mods do
    if let some mIdx := env.getModuleIdx? modName then
      for (cName, cInfo) in env.constants.map₁.toList do
        if env.getModuleIdxFor? cName == some mIdx && !cName.isInternal then
          let sName := cName.toString
          if !sName.endsWith ".rec" && !sName.endsWith ".recOn" && !sName.endsWith ".casesOn"
             && !sName.endsWith ".noConfusion" && !sName.endsWith ".noConfusionType"
             && !sName.endsWith ".below" && !sName.endsWith ".brecOn" && !sName.endsWith ".ctorIdx" then
            let kind := match cInfo with
              | .thmInfo _ => "theorem"
              | .defnInfo _ => "def"
              | .inductInfo _ => "inductive"
              | _ => ""
            if !kind.isEmpty then
              let (fmt, _) ← Core.CoreM.toIO (Meta.MetaM.run' (Meta.ppExpr cInfo.type)) coreCtx coreState
              let sig := (fmt.pretty.replace "\n" " ").replace "\r" ""
              IO.println s!"PREMISE|{modName}|{kind}|{cName}|{sig}"

#eval reflectModules
"""

# Core stdlib arithmetic/list lemmas useful across engineering proofs
BUILTIN_STDLIB_PREMISES: List[PremiseEntry] = [
    PremiseEntry("Nat.add_comm", "add_comm", "theorem", "∀ (n m : Nat), n + m = m + n", "Init.Data.Nat"),
    PremiseEntry("Nat.add_assoc", "add_assoc", "theorem", "∀ (n m k : Nat), n + m + k = n + (m + k)", "Init.Data.Nat"),
    PremiseEntry("Int.add_comm", "add_comm", "theorem", "∀ (a b : Int), a + b = b + a", "Init.Data.Int"),
    PremiseEntry("Int.mul_comm", "mul_comm", "theorem", "∀ (a b : Int), a * b = b * a", "Init.Data.Int"),
    PremiseEntry("Int.mul_nonneg", "mul_nonneg", "theorem", "0 ≤ a → 0 ≤ b → 0 ≤ a * b", "Init.Data.Int"),
    PremiseEntry("Int.natCast_nonneg", "natCast_nonneg", "theorem", "∀ (n : Nat), 0 ≤ (n : Int)", "Init.Data.Int"),
    PremiseEntry("Int.neg_mul_neg", "neg_mul_neg", "theorem", "∀ (a b : Int), (-a) * (-b) = a * b", "Init.Data.Int"),
    PremiseEntry("List.mem_cons_of_mem", "mem_cons_of_mem", "theorem", "a ∈ l → a ∈ b :: l", "Init.Data.List"),
    PremiseEntry("List.length_append", "length_append", "theorem", "(l₁ ++ l₂).length = l₁.length + l₂.length", "Init.Data.List"),
    PremiseEntry("List.foldl_cons", "foldl_cons", "theorem", "List.foldl f init (a :: l) = List.foldl f (f init a) l", "Init.Data.List"),
    PremiseEntry("Bool.and_comm", "and_comm", "theorem", "∀ (a b : Bool), (a && b) = (b && a)", "Init.Data.Bool"),
    PremiseEntry("BitVec.add_comm", "add_comm", "theorem", "∀ (x y : BitVec w), x + y = y + x", "Init.Data.BitVec"),
]


def build_premise_index_from_modules(
    project_root: pathlib.Path,
    modules: Sequence[str],
    *,
    lean_bin: Optional[pathlib.Path] = None,
    include_stdlib_seeds: bool = True,
) -> PremiseIndex:
    """Reflect built `.olean` modules via Lean 4 kernel and return a searchable BM25 PremiseIndex."""
    idx = PremiseIndex(BUILTIN_STDLIB_PREMISES if include_stdlib_seeds else ())
    if not modules:
        return idx

    lean_bin_dir = resolve_lean_bin(project_root, lean_bin)
    lake_exe = lean_bin_dir / ("lake.exe" if os.name == "nt" else "lake")
    env = os.environ.copy()
    env["PATH"] = str(lean_bin_dir) + os.pathsep + env.get("PATH", "")

    mods_lean = ", ".join(f"`{m}" for m in modules)
    script = _REFLECT_PREMISES_TEMPLATE.replace("{MODS}", mods_lean)
    proc = _run_with_transient_oom_retry(
        [str(lake_exe), "env", "lean", "--stdin"],
        input_text=script,
        cwd=project_root,
        env=env,
    )
    if proc.returncode != 0:
        return idx

    for line in (proc.stdout or "").splitlines():
        if not line.startswith("PREMISE|"):
            continue
        parts = line.split("|", 4)
        if len(parts) != 5:
            continue
        _, mod, kind, full_name, sig = parts
        short_name = full_name.rsplit(".", 1)[-1]
        idx.add(PremiseEntry(name=full_name, short_name=short_name, kind=kind, signature=sig, module=mod))

    return idx
