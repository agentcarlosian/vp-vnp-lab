"""Wrapper around Lean 4's native `lake shake` + automatic fallback for non-`module` Lean 4 projects."""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import os
import pathlib
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .dag import ProjectDAG, analyze_project, resolve_lake_executable
from .scheduler import CommitAwareScheduler, SchedulerConfig


@dataclass
class ShakeEdit:
    file_path: str
    remove_imports: List[str] = field(default_factory=list)
    add_imports: List[str] = field(default_factory=list)
    explanations: List[str] = field(default_factory=list)


@dataclass
class ShakeResult:
    command: List[str]
    returncode: int
    raw_output: str
    edits: List[ShakeEdit]
    backend: str = "native-lake-shake"
    backup_dir: Optional[pathlib.Path] = None
    rolled_back_files: List[str] = field(default_factory=list)
    heavy_before: int = 0
    heavy_after: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "backend": self.backend,
            "command": self.command,
            "returncode": self.returncode,
            "files_with_suggestions": len(self.edits),
            "total_removals": sum(len(e.remove_imports) for e in self.edits),
            "total_additions": sum(len(e.add_imports) for e in self.edits),
            "backup_dir": str(self.backup_dir) if self.backup_dir else None,
            "rolled_back_files": list(self.rolled_back_files),
            "heavy_before": self.heavy_before,
            "heavy_after": self.heavy_after,
            "edits": [
                {
                    "file": e.file_path,
                    "remove": e.remove_imports,
                    "add": e.add_imports,
                }
                for e in self.edits
            ],
        }


# Handles both Unix paths and Windows drive-letter paths (e.g. C:\foo\Bar.lean: or Demo/Top.lean:1:0:)
FILE_HEADER_RE = re.compile(r"^((?:[A-Za-z]:)?[^\s].*?\.lean)(?::\d+:\d+)?:\s*(.*)$")
ARRAY_REMOVE_RE = re.compile(r"(?:remove|replace)\s+#\[([^\]]+)\]", re.I)
ARRAY_WITH_RE = re.compile(r"(?:with|add)\s+#\[([^\]]+)\]", re.I)
INLINE_REMOVE_RE = re.compile(
    r"(?:remove|replace)\s+[`']?(?:(?:public|private|meta)\s+)*import\s+(?:all\s+)?([A-Za-z0-9_.']+)[`']?",
    re.I,
)
INLINE_ADD_RE = re.compile(
    r"(?:add|with)\s+[`']?(?:(?:public|private|meta)\s+)*import\s+(?:all\s+)?([A-Za-z0-9_.']+)[`']?",
    re.I,
)
IMPORT_IN_ARRAY_RE = re.compile(
    r"(?:(?:public|private|meta)\s+)*import\s+(?:all\s+)?([A-Za-z0-9_.']+)"
)
BARE_IMPORT_RE = re.compile(
    r"^\s*[-+]?\s*(?:(?:public|private|meta)\s+)*import\s+(?:all\s+)?([A-Za-z0-9_.']+)"
)


def parse_shake_output(output: str) -> List[ShakeEdit]:
    """Parse `lake shake` stdout/stderr across Lean 4.24–4.33 formats (including `#[...]` syntax)."""
    by_file: Dict[str, ShakeEdit] = {}
    current_file: Optional[str] = None
    mode: Optional[str] = None

    def get_edit(fp: str) -> ShakeEdit:
        if fp not in by_file:
            by_file[fp] = ShakeEdit(file_path=fp)
        return by_file[fp]

    def add_unique(lst: List[str], item: str) -> None:
        if item and item not in lst:
            lst.append(item)

    for line in output.splitlines():
        s = line.strip()
        if not s:
            mode = None
            continue

        mh = FILE_HEADER_RE.match(s)
        if mh:
            current_file = mh.group(1)
            rest = mh.group(2)
            ed = get_edit(current_file)
            if "remove" in rest.lower():
                mode = "remove"
                for m in INLINE_REMOVE_RE.finditer(rest):
                    add_unique(ed.remove_imports, m.group(1))
            elif "add" in rest.lower():
                mode = "add"
            else:
                mode = None
            if "unused import" in rest.lower():
                m_u = re.search(r"[`']([A-Za-z0-9_.']+)[`']", rest)
                if m_u:
                    add_unique(ed.remove_imports, m_u.group(1))
            continue

        if current_file is None:
            continue

        ed = get_edit(current_file)
        low = s.lower()

        if "remove these imports" in low or low.startswith("remove:"):
            mode = "remove"
            continue
        if "add these imports" in low or "replace with" in low or low.startswith("add:"):
            mode = "add"
            continue
        if low.startswith("note:") or low.startswith("because ") or "needed for" in low:
            ed.explanations.append(s)
            continue

        # Lean 4.33+ array syntax: `remove #[public import Mini.Unused]` / `replace #[import A] with #[import B]`
        matched_array = False
        for m in ARRAY_REMOVE_RE.finditer(s):
            matched_array = True
            for im in IMPORT_IN_ARRAY_RE.finditer(m.group(1)):
                add_unique(ed.remove_imports, im.group(1))
        for m in ARRAY_WITH_RE.finditer(s):
            matched_array = True
            for im in IMPORT_IN_ARRAY_RE.finditer(m.group(1)):
                add_unique(ed.add_imports, im.group(1))
        if matched_array:
            continue

        # Inline backtick / bare remove/replace directives
        matched_inline = False
        for m in INLINE_REMOVE_RE.finditer(s):
            matched_inline = True
            add_unique(ed.remove_imports, m.group(1))
        for m in INLINE_ADD_RE.finditer(s):
            matched_inline = True
            add_unique(ed.add_imports, m.group(1))
        if matched_inline:
            continue

        mb = BARE_IMPORT_RE.match(line)
        if mb:
            imp = mb.group(1)
            stripped = line.lstrip()
            if stripped.startswith("-") or mode == "remove":
                add_unique(ed.remove_imports, imp)
            elif stripped.startswith("+") or mode == "add":
                add_unique(ed.add_imports, imp)

    return [e for e in by_file.values() if e.remove_imports or e.add_imports]


def _backup_files(project_root: pathlib.Path, files: Sequence[pathlib.Path]) -> pathlib.Path:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = project_root / ".lean-orch-backups" / ts
    bdir.mkdir(parents=True, exist_ok=True)
    for fp in files:
        try:
            rel = fp.resolve().relative_to(project_root.resolve())
        except ValueError:
            continue
        dest = bdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fp, dest)
    return bdir


def _restore_file(project_root: pathlib.Path, backup_dir: pathlib.Path, fp: pathlib.Path) -> bool:
    try:
        rel = fp.resolve().relative_to(project_root.resolve())
    except ValueError:
        return False
    src = backup_dir / rel
    if src.exists():
        shutil.copy2(src, fp)
        return True
    return False


_LEAN_ENV_ANALYZER_TEMPLATE = r"""
import Lean.Meta.Basic
open Lean

def analyzeMod (modName : Name) : IO Unit := do
  initSearchPath (← findSysroot)
  let env ← importModules #[{ module := modName }] {}
  let some targetIdx := env.getModuleIdx? modName | do
    IO.println s!"MOD_ERR:{modName}:not_found"
    return
  let mut usedMods : Std.HashSet Name := {}
  for (cName, cInfo) in env.constants.map₁.toList do
    if env.getModuleIdxFor? cName == some targetIdx then
      let mut refs : Array Name := cInfo.type.getUsedConstants
      if let some val := cInfo.value? then
        refs := refs ++ val.getUsedConstants
      for r in refs do
        if let some rIdx := env.getModuleIdxFor? r then
          if rIdx != targetIdx then
            if h : rIdx.toNat < env.header.moduleNames.size then
              let depMod := env.header.moduleNames[rIdx.toNat]
              usedMods := usedMods.insert depMod
  let sorted := List.mergeSort (List.map (fun (x : Name) => x.toString) usedMods.toList) (· < ·)
  IO.println s!"MOD_DEPS:{modName}:{String.intercalate "," sorted}"

#eval do
  for m in [{MOD_LIST}] do
    analyzeMod m
"""


def _apply_import_edits_to_file(
    fp: pathlib.Path,
    remove_imports: Sequence[str],
    add_imports: Sequence[str],
) -> bool:
    """Safely remove and insert top-level import lines in a Lean file while preserving comments/body."""
    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    rem_set = set(remove_imports)
    new_lines: List[str] = []
    last_import_idx = -1
    changed = False

    import_re = re.compile(r"^\s*(?:(?:public|private|meta)\s+)*import\s+(?:all\s+)?([A-Za-z0-9_.']+)")
    for ln in lines:
        m = import_re.match(ln)
        if m:
            mod = m.group(1)
            if mod in rem_set:
                changed = True
                continue
            last_import_idx = len(new_lines)
        new_lines.append(ln)

    existing_after = set()
    for ln in new_lines:
        m = import_re.match(ln)
        if m:
            existing_after.add(m.group(1))

    to_insert = [f"import {imp}\n" for imp in add_imports if imp not in existing_after]
    if to_insert:
        changed = True
        insert_pos = last_import_idx + 1 if last_import_idx >= 0 else 0
        new_lines[insert_pos:insert_pos] = to_insert

    if changed:
        fp.write_text("".join(new_lines), encoding="utf-8")
    return changed


def _run_lean_env_fallback(
    dag: ProjectDAG,
    lake_exe: pathlib.Path,
    env: Dict[str, str],
    targets: Optional[Sequence[str]],
    *,
    apply_fix: bool,
) -> Tuple[List[ShakeEdit], str, int]:
    """Fallback import minimizer for non-`module` Lean 4 files using Lean.importModules on built `.olean`s."""
    sub = dag.reachable_subgraph(targets)
    built_mods = [m for m in sub if dag.olean_path(m).exists()]
    if not built_mods:
        return [], "No built .olean files found for fallback analysis.", 1

    # Skip pure barrel/aggregator modules (files with imports only and no declarations)
    decl_re = re.compile(
        r"^\s*(?:@\[[^\]]+\]\s*)?(?:noncomputable\s+|protected\s+|private\s+|unsafe\s+|partial\s+)*"
        r"(?:def|theorem|lemma|structure|inductive|class|instance|abbrev|axiom|opaque|example)\b",
        re.MULTILINE,
    )
    candidate_mods = []
    for m in built_mods:
        src = dag.nodes[m].path.read_text(encoding="utf-8", errors="replace")
        if decl_re.search(src) and dag.nodes[m].direct_imports:
            candidate_mods.append(m)

    if not candidate_mods:
        return [], "No non-barrel modules with imports to analyze.", 0

    mod_list_lean = ", ".join(f"`{m}" for m in candidate_mods)
    script = _LEAN_ENV_ANALYZER_TEMPLATE.replace("{MOD_LIST}", mod_list_lean)
    proc = subprocess.run(
        [str(lake_exe), "env", "lean", "--stdin"],
        input=script,
        cwd=str(dag.project_root),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0:
        return [], out, proc.returncode

    # Parse `MOD_DEPS:<mod>:<dep1>,<dep2>,...`
    edits: List[ShakeEdit] = []
    for line in out.splitlines():
        if not line.startswith("MOD_DEPS:"):
            continue
        _, mod, deps_csv = line.split(":", 2)
        if mod not in dag.nodes:
            continue
        used_mods = {d for d in deps_csv.split(",") if d and not d.startswith("Init")}
        node = dag.nodes[mod]
        direct_set = set(node.direct_imports)

        # Keep direct imports whose transitive closure contains a used module, or that are used directly
        def covers_any_used(imp: str) -> bool:
            if imp in used_mods:
                return True
            if imp in dag.nodes:
                # Check if any local transitive dependency of `imp` is used
                stack = [imp]
                seen: Set[str] = set()
                while stack:
                    u = stack.pop()
                    if u in seen:
                        continue
                    seen.add(u)
                    if u in used_mods:
                        return True
                    if u in dag.nodes:
                        stack.extend(dag.nodes[u].local_deps)
            # External non-umbrella prefix check (e.g. Mathlib.Data covers Mathlib.Data.Nat)
            prefix = imp + "."
            return any(u.startswith(prefix) for u in used_mods)

        remove_list = [
            imp for imp in node.direct_imports
            if imp in dag.umbrella_patterns or not covers_any_used(imp)
        ]
        # If removing an umbrella import (like `Mathlib`), add the specific non-local modules used
        add_list: List[str] = []
        if any(imp in dag.umbrella_patterns for imp in remove_list):
            kept_direct = direct_set - set(remove_list)
            for u in sorted(used_mods):
                if u not in kept_direct and u != mod:
                    add_list.append(u)

        if remove_list or add_list:
            edits.append(
                ShakeEdit(
                    file_path=str(node.path),
                    remove_imports=remove_list,
                    add_imports=add_list,
                    explanations=[f"Constant-level olean analysis found {len(used_mods)} referenced defining modules."],
                )
            )
            if apply_fix:
                _apply_import_edits_to_file(node.path, remove_list, add_list)

    return edits, out, 0


def run_lake_shake(
    dag: ProjectDAG,
    targets: Optional[Sequence[str]] = None,
    *,
    apply_fix: bool = False,
    explain: bool = True,
    keep_public: bool = False,
    keep_prefix: bool = False,
    keep_implied: bool = False,
    force: bool = True,
    verify_after_fix: bool = True,
    lean_bin: Optional[pathlib.Path] = None,
    scheduler_config: Optional[SchedulerConfig] = None,
) -> ShakeResult:
    """Run Lean 4's native `lake shake`, falling back to `.olean` env analysis on non-`module` projects."""
    lake_exe, lean_bin_dir = resolve_lake_executable(dag.project_root, lean_bin)
    env = os.environ.copy()
    if lean_bin_dir is not None:
        env["PATH"] = str(lean_bin_dir) + os.pathsep + env.get("PATH", "")

    heavy_before = sum(1 for n in dag.nodes.values() if n.weight_class == "heavy")

    cmd: List[str] = [str(lake_exe), "shake"]
    if force:
        cmd.append("--force")
    if explain:
        cmd.append("--explain")
    if keep_public:
        cmd.append("--keep-public")
    if keep_prefix:
        cmd.append("--keep-prefix")
    if keep_implied:
        cmd.append("--keep-implied")

    backup_dir: Optional[pathlib.Path] = None
    if apply_fix:
        sub = dag.reachable_subgraph(targets)
        backup_dir = _backup_files(dag.project_root, [dag.nodes[m].path for m in sub])
        cmd.append("--fix")

    if targets:
        cmd.extend(targets)

    proc = subprocess.run(
        cmd,
        cwd=str(dag.project_root),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    backend = "native-lake-shake"
    returncode = proc.returncode

    if "only works with `module`s" in combined:
        backend = "lean-env-fallback"
        edits, fb_out, returncode = _run_lean_env_fallback(
            dag, lake_exe, env, targets, apply_fix=apply_fix
        )
        combined = combined.strip() + "\n[fallback: lean-env-analyzer]\n" + fb_out
    else:
        edits = parse_shake_output(combined)

    rolled_back: List[str] = []
    heavy_after = heavy_before

    if apply_fix:
        new_dag = analyze_project(dag.project_root)
        heavy_after = sum(1 for n in new_dag.nodes.values() if n.weight_class == "heavy")

        if verify_after_fix and backup_dir is not None:
            cfg = scheduler_config or SchedulerConfig(
                lean_bin=lean_bin,
                force_rebuild=False,
            )
            sched = CommitAwareScheduler(new_dag, cfg)
            summary = sched.run(targets)
            if summary.failed_modules:
                for failed_mod in summary.failed_modules:
                    if failed_mod in new_dag.nodes:
                        fp = new_dag.nodes[failed_mod].path
                        if _restore_file(dag.project_root, backup_dir, fp):
                            rolled_back.append(failed_mod)
                after_rb = analyze_project(dag.project_root)
                heavy_after = sum(1 for n in after_rb.nodes.values() if n.weight_class == "heavy")

    return ShakeResult(
        command=cmd,
        returncode=returncode,
        raw_output=combined,
        edits=edits,
        backend=backend,
        backup_dir=backup_dir,
        rolled_back_files=rolled_back,
        heavy_before=heavy_before,
        heavy_after=heavy_after,
    )
