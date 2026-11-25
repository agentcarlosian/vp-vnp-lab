"""Configuration loader for `pcvh.toml`."""

from __future__ import annotations

from dataclasses import dataclass, field
import pathlib
import tomllib
from typing import List, Optional

DEFAULT_ALLOWED_AXIOMS = ["propext", "Classical.choice", "Quot.sound"]
DEFAULT_FORBIDDEN_UMBRELLAS = ["Mathlib", "Mathlib.Tactic", "Mathlib.All"]


@dataclass
class SpecConfig:
    project_root: pathlib.Path
    name: str
    lean_toolchain: str
    statement_rel: str
    challenge_rel: str
    challenge_module: str
    solution_module: str
    allowed_axioms: List[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_AXIOMS))
    forbid_umbrella_imports: List[str] = field(default_factory=lambda: list(DEFAULT_FORBIDDEN_UMBRELLAS))
    require_nonvacuity_witness: bool = True
    nonvacuity_suffix: str = "nonvacuous"
    conformance_command: Optional[str] = None
    falsification_enabled: bool = True
    falsification_command: Optional[str] = None
    falsification_max_seconds: int = 30
    falsification_lean_samples: int = 64
    max_rounds_per_lemma: int = 8
    max_token_budget_usd: float = 5.0
    auto_lake_shake: bool = True
    extra_tcb_files: List[str] = field(default_factory=list)
    target_language: str = "python"
    target_template: str = "custom"
    enable_tree_search: bool = True
    max_parallel_workers: int = 2
    require_dual_kernel: bool = False

    @property
    def tcb_rel_paths(self) -> List[str]:
        base = [
            "pcvh.toml",
            "lean-toolchain",
            self.statement_rel,
            self.challenge_rel,
        ]
        for cand in ("lakefile.toml", "lakefile.lean", "lake-manifest.json", "conformance_fuzz.py"):
            if (self.project_root / cand).exists():
                base.append(cand)
        for ex in self.extra_tcb_files:
            if ex not in base:
                base.append(ex)
        return base


def load_spec_config(project_root: pathlib.Path) -> SpecConfig:
    root = pathlib.Path(project_root).resolve()
    cfg_path = root / "pcvh.toml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"Missing pcvh.toml in {root}")
    raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    spec = raw.get("spec", {})
    loop = raw.get("agent_loop", {})
    conf = raw.get("conformance", {})
    fals = raw.get("falsification", {})
    tgt = raw.get("target", {})
    dk = raw.get("dual_kernel", {})

    return SpecConfig(
        project_root=root,
        name=str(spec.get("name", root.name)),
        lean_toolchain=str(spec.get("lean_toolchain", "leanprover/lean4:v4.33.1")),
        statement_rel=str(spec["statement"]),
        challenge_rel=str(spec["challenge"]),
        challenge_module=str(spec["challenge_module"]),
        solution_module=str(spec.get("solution_module", "Solution")),
        allowed_axioms=list(spec.get("allowed_axioms", DEFAULT_ALLOWED_AXIOMS)),
        forbid_umbrella_imports=list(loop.get("forbid_umbrella_imports", DEFAULT_FORBIDDEN_UMBRELLAS)),
        require_nonvacuity_witness=bool(spec.get("require_nonvacuity_witness", True)),
        nonvacuity_suffix=str(spec.get("nonvacuity_suffix", "nonvacuous")),
        conformance_command=conf.get("command"),
        falsification_enabled=bool(fals.get("enabled", True)),
        falsification_command=fals.get("command"),
        falsification_max_seconds=int(fals.get("max_seconds", 30)),
        falsification_lean_samples=int(fals.get("lean_samples", 64)),
        max_rounds_per_lemma=int(loop.get("max_rounds_per_lemma", 8)),
        max_token_budget_usd=float(loop.get("max_token_budget_usd", 5.0)),
        auto_lake_shake=bool(loop.get("auto_lake_shake", True)),
        extra_tcb_files=list(spec.get("extra_tcb_files", [])),
        target_language=str(tgt.get("language", "python")),
        target_template=str(tgt.get("template", "custom")),
        enable_tree_search=bool(loop.get("enable_tree_search", True)),
        max_parallel_workers=int(loop.get("max_parallel_workers", 2)),
        require_dual_kernel=bool(dk.get("required", False)),
    )
