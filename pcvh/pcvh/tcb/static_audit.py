"""Comment-aware static anti-cheating scanner for untrusted Lean 4 proof packages."""

from __future__ import annotations

from dataclasses import dataclass, field
import pathlib
import re
from typing import Dict, List, Sequence, Set, Tuple

from ..config import SpecConfig

SKIP_DIRS = {".lake", ".git", ".pcvh_tcb_snapshot", ".lean-orch-backups", "__pycache__"}


@dataclass(frozen=True)
class AuditViolation:
    file: str
    line: int
    rule: str
    snippet: str


@dataclass
class StaticAuditResult:
    ok: bool
    files_scanned: int
    violations: List[AuditViolation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "files_scanned": self.files_scanned,
            "violation_count": len(self.violations),
            "violations": [
                {"file": v.file, "line": v.line, "rule": v.rule, "snippet": v.snippet}
                for v in self.violations
            ],
        }


def strip_lean_comments_and_strings(source: str) -> str:
    """Replace Lean comments (`--`, nested `/- ... -/`) and string literals with spaces, preserving line numbers."""
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
                out.append("  ")
                i += 2
            elif ch == "-" and nxt == "/":
                block_depth -= 1
                out.append("  ")
                i += 2
            elif ch == "\n":
                out.append("\n")
                i += 1
            else:
                out.append(" ")
                i += 1
            continue

        if in_string:
            if ch == "\\" and i + 1 < n:
                out.append("  ")
                i += 2
                continue
            if ch == '"':
                in_string = False
                out.append(" ")
            elif ch == "\n":
                out.append("\n")
            else:
                out.append(" ")
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(" ")
            i += 1
            continue

        if ch == "-" and nxt == "-":
            while i < n and source[i] != "\n":
                out.append(" ")
                i += 1
            continue

        if ch == "/" and nxt == "-":
            block_depth = 1
            out.append("  ")
            i += 2
            continue

        out.append(ch)
        i += 1

    return "".join(out)


BANNED_RULES: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("banned_sorry", re.compile(r"\bsorry\b")),
    ("banned_admit", re.compile(r"\badmit\b")),
    ("banned_custom_axiom", re.compile(r"(?:^|\s)axiom\s+[A-Za-z_«]")),
    ("banned_native_decide", re.compile(r"\bnative_decide\b")),
    ("banned_unsafe", re.compile(r"\bunsafe\b")),
    ("banned_implemented_by", re.compile(r"\bimplemented_by\b")),
    ("banned_extern", re.compile(r"@\[[^\]]*\bextern\b")),
    ("banned_ofReduceBool", re.compile(r"\bofReduceBool\b|\bofReduceNat\b")),
    ("banned_env_addDecl", re.compile(r"\b(?:addDecl|addAndCompile|addAxiom|setEnv)\b")),
    ("banned_debug_skip_kernel", re.compile(r"set_option\s+debug\.skipKernelTC\b")),
)

IMPORT_RE = re.compile(
    r"^\s*(?:(?:public|private|meta)\s+)*import\s+(?:all\s+)?([A-Za-z_][A-Za-z0-9_.']*)"
)


def scan_untrusted_lean_files(
    workspace_root: pathlib.Path,
    cfg: SpecConfig,
    exempt_rel_paths: Optional[Sequence[str]] = None,
) -> StaticAuditResult:
    """Scan all non-TCB `.lean` files in `workspace_root` for proof-cheating constructs and forbidden imports."""
    exempt: Set[str] = {
        cfg.challenge_rel.replace("\\", "/"),
        "lakefile.lean",
    }
    if exempt_rel_paths:
        exempt |= {p.replace("\\", "/") for p in exempt_rel_paths}

    forbidden_umb = set(cfg.forbid_umbrella_imports)
    violations: List[AuditViolation] = []
    scanned = 0

    for fp in sorted(workspace_root.rglob("*.lean")):
        rel = fp.relative_to(workspace_root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        rel_str = rel.as_posix()
        if rel_str in exempt:
            continue

        scanned += 1
        raw = fp.read_text(encoding="utf-8", errors="replace")
        cleaned = strip_lean_comments_and_strings(raw)
        raw_lines = raw.splitlines()
        clean_lines = cleaned.splitlines()

        for idx, cline in enumerate(clean_lines, start=1):
            rline = raw_lines[idx - 1].strip() if idx - 1 < len(raw_lines) else ""
            for rule_name, pat in BANNED_RULES:
                if pat.search(cline):
                    violations.append(
                        AuditViolation(file=rel_str, line=idx, rule=rule_name, snippet=rline[:120])
                    )

            m_imp = IMPORT_RE.match(cline)
            if m_imp and m_imp.group(1) in forbidden_umb:
                violations.append(
                    AuditViolation(
                        file=rel_str,
                        line=idx,
                        rule="forbidden_umbrella_import",
                        snippet=rline[:120],
                    )
                )

    return StaticAuditResult(ok=(len(violations) == 0), files_scanned=scanned, violations=violations)
