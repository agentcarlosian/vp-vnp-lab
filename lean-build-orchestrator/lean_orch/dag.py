"""Lake project discovery, comment-aware Lean 4 import DAG, and umbrella-import blast-radius analysis."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import os
import pathlib
import re
import shutil
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .memory import OleanFootprint, measure_olean_footprint

DEFAULT_UMBRELLA_IMPORTS = (
    "Mathlib",
    "Mathlib.Tactic",
    "Mathlib.All",
)

MEDIUM_PREFIXES = (
    "Mathlib.",
    "Batteries",
    "Aesop",
    "Qq",
)

IMPORT_LINE_RE = re.compile(
    r"^\s*(?:(?:public|private|meta)\s+)*import\s+(?:all\s+)?([A-Za-z_][A-Za-z0-9_'.]*)",
    re.MULTILINE,
)

EXCLUDED_DIRS = {".lake", ".git", ".elan", "build", "__pycache__", ".lean-orch-backups"}


def strip_lean_comments(source: str) -> str:
    """Strip `-- ...` line comments and nested `/- ... -/` block comments from Lean 4 source."""
    out: List[str] = []
    i = 0
    n = len(source)
    block_depth = 0
    in_string = False

    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""

        if block_depth > 0:
            if ch == "/" and nxt == "-":
                block_depth += 1
                i += 2
            elif ch == "-" and nxt == "/":
                block_depth -= 1
                i += 2
            elif ch == "\n":
                out.append("\n")
                i += 1
            else:
                i += 1
            continue

        if in_string:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                in_string = False
            elif ch == "\n":
                out.append("\n")
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append('"')
            i += 1
            continue

        if ch == "-" and nxt == "-":
            while i < n and source[i] != "\n":
                i += 1
            continue

        if ch == "/" and nxt == "-":
            block_depth = 1
            i += 2
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def parse_imports(source: str) -> List[str]:
    """Extract top-level Lean 4 imports from source (ignoring comments and module body)."""
    cleaned = strip_lean_comments(source)
    imports: List[str] = []
    seen: Set[str] = set()
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in ("module", "prelude"):
            continue
        m = IMPORT_LINE_RE.match(raw_line)
        if m:
            mod = m.group(1)
            if mod not in seen:
                seen.add(mod)
                imports.append(mod)
            continue
        # Stop scanning once declarations/commands start after header
        if re.match(
            r"^(?:namespace|section|open|variable|universe|def|theorem|lemma|structure|"
            r"inductive|class|instance|abbrev|axiom|opaque|noncomputable|protected|private|"
            r"attribute|set_option|#|macro|syntax|elab|declare_syntax_cat|notation|infix)",
            line,
        ):
            break
    return imports


def read_toolchain(project_root: pathlib.Path) -> Optional[str]:
    tc = project_root / "lean-toolchain"
    if tc.exists():
        return tc.read_text(encoding="utf-8", errors="replace").strip()
    return None


def resolve_lake_executable(
    project_root: pathlib.Path,
    lean_bin: Optional[pathlib.Path] = None,
) -> Tuple[pathlib.Path, Optional[pathlib.Path]]:
    """Locate `lake` executable and its bin directory without triggering network elan shims when possible."""
    exe_name = "lake.exe" if os.name == "nt" else "lake"

    if lean_bin is not None:
        cand = pathlib.Path(lean_bin) / exe_name
        if cand.exists():
            return cand, pathlib.Path(lean_bin)

    toolchain = read_toolchain(project_root)
    tc_dir_name = None
    if toolchain:
        # e.g. leanprover/lean4:v4.33.1 -> leanprover--lean4---v4.33.1
        tc_dir_name = toolchain.replace("/", "--").replace(":", "---")

    # Search candidate ELAN_HOME roots (env, parent isolated .elan, user ~/.elan)
    elan_candidates: List[pathlib.Path] = []
    if os.environ.get("ELAN_HOME"):
        elan_candidates.append(pathlib.Path(os.environ["ELAN_HOME"]))
    for ancestor in [project_root, *project_root.parents[:4]]:
        local_elan = ancestor / ".elan"
        if local_elan.exists():
            elan_candidates.append(local_elan)
    home_elan = pathlib.Path.home() / ".elan"
    if home_elan.exists():
        elan_candidates.append(home_elan)

    if tc_dir_name:
        for elan_home in elan_candidates:
            direct = elan_home / "toolchains" / tc_dir_name / "bin" / exe_name
            if direct.exists():
                return direct, direct.parent

    # Fall back to any installed toolchain inside detected ELAN_HOME or PATH
    for elan_home in elan_candidates:
        tc_root = elan_home / "toolchains"
        if tc_root.exists():
            for child in sorted(tc_root.iterdir(), reverse=True):
                cand = child / "bin" / exe_name
                if cand.exists():
                    return cand, cand.parent

    which_lake = shutil.which("lake")
    if which_lake:
        p = pathlib.Path(which_lake)
        return p, p.parent

    raise FileNotFoundError(
        f"Could not locate `{exe_name}`. Pass --lean-bin or set ELAN_HOME."
    )


def discover_src_dir(project_root: pathlib.Path) -> pathlib.Path:
    """Detect `srcDir` from lakefile.toml / lakefile.lean if configured, else project_root."""
    toml_fp = project_root / "lakefile.toml"
    if toml_fp.exists():
        txt = toml_fp.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'^\s*srcDir\s*=\s*"([^"]+)"', txt, re.M)
        if m:
            cand = project_root / m.group(1)
            if cand.exists():
                return cand
    lean_fp = project_root / "lakefile.lean"
    if lean_fp.exists():
        txt = lean_fp.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'srcDir\s*:=\s*"([^"]+)"', txt)
        if m:
            cand = project_root / m.group(1)
            if cand.exists():
                return cand
    return project_root


def discover_default_targets(project_root: pathlib.Path, local_modules: Set[str]) -> List[str]:
    """Detect default Lake targets or top-level roots if none specified."""
    targets: List[str] = []
    toml_fp = project_root / "lakefile.toml"
    if toml_fp.exists():
        txt = toml_fp.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'defaultTargets\s*=\s*\[([^\]]+)\]', txt)
        if m:
            for item in re.findall(r'"([^"]+)"', m.group(1)):
                if item in local_modules:
                    targets.append(item)
    lean_fp = project_root / "lakefile.lean"
    if not targets and lean_fp.exists():
        txt = lean_fp.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"@\[default_target\][\s\S]{0,200}?(?:lean_lib|lean_exe)\s+«?([A-Za-z0-9_]+)»?", txt):
            name = m.group(1)
            if name in local_modules:
                targets.append(name)
            else:
                # Include all modules under this lib root
                pref = name + "."
                targets.extend(sorted(mod for mod in local_modules if mod.startswith(pref)))
    if not targets:
        # Top-level roots (modules without dots, or all sinks)
        roots = sorted(m for m in local_modules if "." not in m)
        targets = roots if roots else sorted(local_modules)
    return sorted(set(targets))


@dataclass
class ModuleNode:
    name: str
    path: pathlib.Path
    line_count: int
    direct_imports: List[str]
    local_deps: List[str]
    external_deps: List[str]
    direct_umbrellas: List[str] = field(default_factory=list)
    transitive_umbrellas: Set[str] = field(default_factory=set)
    weight_class: str = "light"  # "heavy" | "medium" | "light"
    estimated_commit_gb: float = 0.4
    critical_path_depth: int = 1
    olean_exists: bool = False
    olean_fresh: bool = False


@dataclass
class UmbrellaOffenderReport:
    module: str
    path: str
    direct_umbrellas: List[str]
    downstream_poisoned_count: int
    exclusively_poisoned_count: int  # modules freed from umbrella if THIS single file is shaken


@dataclass
class ProjectDAG:
    project_root: pathlib.Path
    src_dir: pathlib.Path
    toolchain: Optional[str]
    nodes: Dict[str, ModuleNode]
    rdeps: Dict[str, List[str]]
    topo_levels: List[List[str]]
    footprint: OleanFootprint
    umbrella_patterns: Tuple[str, ...]
    heavy_worker_gb: float
    medium_worker_gb: float
    light_worker_gb: float

    def olean_path(self, mod: str) -> pathlib.Path:
        return (
            self.project_root
            / ".lake"
            / "build"
            / "lib"
            / "lean"
            / (mod.replace(".", os.sep) + ".olean")
        )

    def reachable_subgraph(self, targets: Optional[Sequence[str]] = None) -> List[str]:
        if not targets:
            return [m for lv in self.topo_levels for m in lv]
        wanted: Set[str] = set()
        stack: List[str] = []
        for t in targets:
            if t in self.nodes:
                stack.append(t)
            else:
                # Allow library prefix target like "Paper" -> Paper.*
                pref = t + "."
                matched = [m for m in self.nodes if m.startswith(pref)]
                stack.extend(matched)
        while stack:
            u = stack.pop()
            if u in wanted or u not in self.nodes:
                continue
            wanted.add(u)
            stack.extend(self.nodes[u].local_deps)
        return [m for lv in self.topo_levels for m in lv if m in wanted]

    def umbrella_blast_radius(self) -> List[UmbrellaOffenderReport]:
        """Rank every direct umbrella-importing module by downstream poison & exclusive unlock impact."""
        direct_offenders = sorted(
            m for m, node in self.nodes.items() if node.direct_umbrellas
        )
        if not direct_offenders:
            return []

        def poisoned_without(excluded: Optional[str]) -> Set[str]:
            seeds = [m for m in direct_offenders if m != excluded]
            visited: Set[str] = set()
            stack = list(seeds)
            while stack:
                u = stack.pop()
                if u in visited:
                    continue
                visited.add(u)
                stack.extend(self.rdeps.get(u, []))
            return visited

        baseline = poisoned_without(None)
        reports: List[UmbrellaOffenderReport] = []
        for mod in direct_offenders:
            # Downstream reachable from this single offender
            down: Set[str] = set()
            st = [mod]
            while st:
                u = st.pop()
                if u in down:
                    continue
                down.add(u)
                st.extend(self.rdeps.get(u, []))
            without_me = poisoned_without(mod)
            exclusive = len(baseline - without_me)
            reports.append(
                UmbrellaOffenderReport(
                    module=mod,
                    path=str(self.nodes[mod].path),
                    direct_umbrellas=list(self.nodes[mod].direct_umbrellas),
                    downstream_poisoned_count=len(down),
                    exclusively_poisoned_count=exclusive,
                )
            )
        reports.sort(
            key=lambda r: (-r.exclusively_poisoned_count, -r.downstream_poisoned_count, r.module)
        )
        return reports

    def summary_dict(self, targets: Optional[Sequence[str]] = None) -> Dict[str, object]:
        sub = self.reachable_subgraph(targets)
        heavy = [m for m in sub if self.nodes[m].weight_class == "heavy"]
        medium = [m for m in sub if self.nodes[m].weight_class == "medium"]
        light = [m for m in sub if self.nodes[m].weight_class == "light"]
        built = [m for m in sub if self.nodes[m].olean_fresh]
        direct_umb = [m for m in sub if self.nodes[m].direct_umbrellas]
        return {
            "project_root": str(self.project_root),
            "toolchain": self.toolchain,
            "total_modules": len(sub),
            "topo_levels": len(self.topo_levels),
            "built_fresh": len(built),
            "remaining": len(sub) - len(built),
            "heavy_modules": len(heavy),
            "medium_modules": len(medium),
            "light_modules": len(light),
            "direct_umbrella_offenders": len(direct_umb),
            "estimated_weights_gb": {
                "heavy": self.heavy_worker_gb,
                "medium": self.medium_worker_gb,
                "light": self.light_worker_gb,
            },
            "olean_footprint": self.footprint.to_dict(),
        }


def analyze_project(
    project_root: pathlib.Path,
    umbrella_patterns: Sequence[str] = DEFAULT_UMBRELLA_IMPORTS,
    heavy_worker_gb: Optional[float] = None,
    medium_worker_gb: float = 2.2,
    light_worker_gb: float = 0.45,
    exclude_dirs: Iterable[str] = ("scripts",),
) -> ProjectDAG:
    """Scan a Lean 4 Lake project and build its full dependency & commit-weight DAG."""
    project_root = pathlib.Path(project_root).resolve()
    src_dir = discover_src_dir(project_root)
    toolchain = read_toolchain(project_root)
    footprint = measure_olean_footprint(project_root)

    if heavy_worker_gb is None:
        heavy_worker_gb = max(
            1.5, footprint.estimated_windows_commit_per_umbrella_worker_gb()
        )
        # If no external Mathlib package is present, keep realistic stdlib weight
        if footprint.total_bytes < 50 * 1024 * 1024:
            heavy_worker_gb = 1.5

    skip_names = EXCLUDED_DIRS | set(exclude_dirs)
    local_files: Dict[str, pathlib.Path] = {}
    for fp in src_dir.rglob("*.lean"):
        rel = fp.relative_to(src_dir)
        if any(part in skip_names for part in rel.parts[:-1]):
            continue
        if rel.name == "lakefile.lean":
            continue
        mod = ".".join(rel.with_suffix("").parts)
        local_files[mod] = fp

    umbrella_set = tuple(umbrella_patterns)
    nodes: Dict[str, ModuleNode] = {}
    for mod, fp in sorted(local_files.items()):
        txt = fp.read_text(encoding="utf-8", errors="replace")
        imps = parse_imports(txt)
        local_deps = [imp for imp in imps if imp in local_files and imp != mod]
        ext_deps = [imp for imp in imps if imp not in local_files]
        direct_umb = [imp for imp in ext_deps if imp in umbrella_set]

        olean_fp = (
            project_root
            / ".lake"
            / "build"
            / "lib"
            / "lean"
            / (mod.replace(".", os.sep) + ".olean")
        )
        olean_exists = olean_fp.exists()
        olean_fresh = False
        if olean_exists:
            try:
                olean_fresh = olean_fp.stat().st_mtime >= fp.stat().st_mtime
            except OSError:
                olean_fresh = False

        nodes[mod] = ModuleNode(
            name=mod,
            path=fp,
            line_count=txt.count("\n") + (1 if txt else 0),
            direct_imports=imps,
            local_deps=local_deps,
            external_deps=ext_deps,
            direct_umbrellas=direct_umb,
            olean_exists=olean_exists,
            olean_fresh=olean_fresh,
        )

    # Kahn topological sort
    indeg: Dict[str, int] = {m: 0 for m in nodes}
    rdeps: Dict[str, List[str]] = defaultdict(list)
    for m, node in nodes.items():
        for d in node.local_deps:
            indeg[m] += 1
            rdeps[d].append(m)

    topo_levels: List[List[str]] = []
    q = sorted(m for m, deg in indeg.items() if deg == 0)
    visited_cnt = 0
    while q:
        topo_levels.append(q)
        visited_cnt += len(q)
        nxt: List[str] = []
        for u in q:
            for v in rdeps[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    nxt.append(v)
        q = sorted(nxt)

    if visited_cnt != len(nodes):
        # Include any cycle members at the end so audit never crashes on malformed sources
        seen = {m for lv in topo_levels for m in lv}
        rem = sorted(m for m in nodes if m not in seen)
        if rem:
            topo_levels.append(rem)

    # Propagate transitive umbrellas & transitive freshness forward in topological order
    trans_ext: Dict[str, Set[str]] = {}
    for lv in topo_levels:
        for m in lv:
            node = nodes[m]
            t_umb = set(node.direct_umbrellas)
            t_ext = set(node.external_deps)
            all_deps_fresh = True
            for d in node.local_deps:
                t_umb |= nodes[d].transitive_umbrellas
                t_ext |= trans_ext.get(d, set())
                if not nodes[d].olean_fresh:
                    all_deps_fresh = False
            node.transitive_umbrellas = t_umb
            trans_ext[m] = t_ext
            if node.olean_fresh and not all_deps_fresh:
                # Stale relative to an unbuilt/newer dependency
                node.olean_fresh = False

            if t_umb:
                node.weight_class = "heavy"
                node.estimated_commit_gb = heavy_worker_gb
            elif any(
                any(ext == pref or ext.startswith(pref) for pref in MEDIUM_PREFIXES)
                for ext in t_ext
            ):
                node.weight_class = "medium"
                node.estimated_commit_gb = medium_worker_gb
            else:
                node.weight_class = "light"
                node.estimated_commit_gb = light_worker_gb

    # Critical-path depth (longest path to any sink, computed bottom-up)
    for lv in reversed(topo_levels):
        for m in lv:
            children = rdeps.get(m, [])
            if not children:
                nodes[m].critical_path_depth = 1
            else:
                nodes[m].critical_path_depth = 1 + max(
                    nodes[c].critical_path_depth for c in children
                )

    return ProjectDAG(
        project_root=project_root,
        src_dir=src_dir,
        toolchain=toolchain,
        nodes=nodes,
        rdeps=dict(rdeps),
        topo_levels=topo_levels,
        footprint=footprint,
        umbrella_patterns=umbrella_set,
        heavy_worker_gb=heavy_worker_gb,
        medium_worker_gb=medium_worker_gb,
        light_worker_gb=light_worker_gb,
    )
