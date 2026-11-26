"""Comment-aware static anti-cheating scanner for untrusted Lean 4 proof packages."""

from __future__ import annotations

from dataclasses import dataclass, field
import pathlib
import re
from typing import Dict, List, Sequence, Set, Tuple

from ..config import SpecConfig

SKIP_DIRS = {
    ".lake",
    ".git",
    ".pcvh_tcb_snapshot",
    ".lean-orch-backups",
    "__pycache__",
    "target",
    "node_modules",
    "out",
    "cache",
    "broadcast",
}


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


def _match_lean_char_literal(source: str, i: int) -> int:
    """Return length of a Lean 4 character literal starting at `i`, or 0 if not one."""
    n = len(source)
    if source[i] != "'" or i + 2 >= n:
        return 0
    if i > 0 and (source[i - 1].isalnum() or source[i - 1] in "_'"):
        return 0
    nxt = source[i + 1]
    if nxt == "\n" or nxt == "'":
        return 0
    if nxt == "\\":
        if i + 3 < n and source[i + 2] == "x":
            if i + 5 < n and all(c in "0123456789abcdefABCDEF" for c in source[i + 3 : i + 5]) and source[i + 5] == "'":
                return 6
            return 0
        if i + 3 < n and source[i + 2] == "u":
            if i + 7 < n and all(c in "0123456789abcdefABCDEF" for c in source[i + 3 : i + 7]) and source[i + 7] == "'":
                return 8
            return 0
        if i + 3 < n and source[i + 2] != "\n" and source[i + 3] == "'":
            return 4
        return 0
    if source[i + 2] == "'":
        return 3
    return 0


def _match_lean_raw_string_prefix(source: str, i: int) -> int:
    """Return `#` count for Lean 4 raw string `r#\"...\"#` at `i`, or 0 if not one."""
    n = len(source)
    if source[i] != "r":
        return 0
    if i > 0 and (source[i - 1].isalnum() or source[i - 1] in "_'"):
        return 0
    j = i + 1
    while j < n and source[j] == "#":
        j += 1
    hashes = j - (i + 1)
    if hashes > 0 and j < n and source[j] == '"':
        return hashes
    return 0


def strip_lean_comments_and_strings(source: str) -> str:
    """Replace Lean comments (`--`, nested `/- ... -/`), char literals, raw strings, and string literals with spaces, preserving line numbers."""
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
                if source[i + 1] == "\n":
                    out.append(" \n")
                else:
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

        char_len = _match_lean_char_literal(source, i)
        if char_len:
            out.append(" " * char_len)
            i += char_len
            continue

        raw_hashes = _match_lean_raw_string_prefix(source, i)
        if raw_hashes:
            prefix_len = 2 + raw_hashes
            out.append(" " * prefix_len)
            i += prefix_len
            closing = '"' + ("#" * raw_hashes)
            while i < n:
                if source.startswith(closing, i):
                    out.append(" " * len(closing))
                    i += len(closing)
                    break
                out.append("\n" if source[i] == "\n" else " ")
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
    ("banned_extern", re.compile(r"@\[[^\]]*\b(?:extern|csimp)\b")),
    ("banned_ofReduceBool", re.compile(r"\bofReduceBool\b|\bofReduceNat\b")),
    ("banned_env_addDecl", re.compile(r"\b(?:addDecl|addAndCompile|addAxiom|setEnv)\b")),
    (
        "banned_compile_time_exec",
        re.compile(
            r"(?:^|\s)(?:#eval|run_cmd|elab|elab_rules|command_elab|term_elab|tactic_elab|macro|macro_rules|syntax|initialize|builtin_initialize)\b"
        ),
    ),
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
        cfg.statement_rel.replace("\\", "/"),
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
            # Normalize Lean French guillemets (`«sorry»` -> ` sorry `) so escaped identifiers cannot evade `\b`
            norm_line = cline.replace("«", " ").replace("»", " ")
            rline = raw_lines[idx - 1].strip() if idx - 1 < len(raw_lines) else ""
            for rule_name, pat in BANNED_RULES:
                if pat.search(norm_line):
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
