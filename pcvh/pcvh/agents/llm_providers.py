"""Real multi-provider LLM backends for PCVH Tier-3 proof repair & tree-search expansion.

Supports:
  - Anthropic Messages API (`ANTHROPIC_API_KEY`, e.g. `claude-sonnet-4-20250514` / `claude-opus-4-20250514`)
  - OpenAI Chat Completions API (`OPENAI_API_KEY` / `PCVH_LLM_API_KEY`, e.g. `gpt-4.1-mini` / `o4-mini`)
  - Local Ollama REST API (`OLLAMA_HOST`, default `http://127.0.0.1:11434`, zero API key, $0.00 cost)
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .prover import LLMBackend, ProofPromptContext


def _urlopen_smart(req: urllib.request.Request, timeout: float):
    """Bypass HTTP_PROXY automatically for loopback (`127.0.0.1` / `localhost`) endpoints such as local Ollama."""
    host = (urllib.parse.urlparse(req.full_url).hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def _clean_tactic_response(text: str) -> str:
    content = text.strip()
    content = re.sub(r"^```(?:lean4?)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    if content.startswith("by\n"):
        content = content[3:]
    elif content.startswith("by "):
        content = content[3:]
    return content.strip()


def _parse_step_candidates(raw_text: str, max_k: int = 4) -> List[str]:
    """Parse multi-branch tactic candidates from JSON array or newline/bullet list."""
    cleaned = _clean_tactic_response(raw_text)
    if not cleaned:
        return []
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            out = [_clean_tactic_response(str(x)) for x in parsed if str(x).strip()]
            return out[:max_k]
    except json.JSONDecodeError:
        pass
    out: List[str] = []
    for line in cleaned.splitlines():
        s = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        s = s.strip("`").strip()
        if s and not s.startswith("--"):
            out.append(s)
        if len(out) >= max_k:
            break
    return out


def _build_full_proof_messages(ctx: ProofPromptContext) -> Tuple[str, str]:
    system_msg = (
        "You are an expert Lean 4.33 theorem prover. Output ONLY valid Lean 4 tactic lines "
        "(no markdown fences, no leading `by`, no `sorry`, no `admit`, no `axiom`, no `native_decide`)."
    )
    parts = [
        f"Target theorem:\n{ctx.theorem_signature} := by",
        "Current Lean 4 infoview goals:\n" + ("\n".join(ctx.live_lsp_goals) or "(none)"),
        f"Relevant verified premises:\n{ctx.retrieved_premises_text}",
    ]
    if ctx.previous_attempt:
        parts.append(f"Previous failed attempt:\n{ctx.previous_attempt}")
    if ctx.previous_errors:
        parts.append("Lean 4 errors:\n" + "\n".join(ctx.previous_errors[:6]))
    return system_msg, "\n\n".join(parts)


def _build_tree_step_messages(
    theorem_signature: str,
    tactic_prefix: Sequence[str],
    active_goals: Sequence[str],
    premises_text: str,
    k: int = 4,
) -> Tuple[str, str]:
    system_msg = (
        f"You are a Lean 4 tactic search policy. Propose up to {k} distinct single-step Lean 4 tactics "
        "to advance or close the first active goal. Return ONLY a JSON array of strings (no `sorry`, "
        "`admit`, `axiom`, or `native_decide`)."
    )
    prefix_txt = "\n".join(tactic_prefix) if tactic_prefix else "(start of proof)"
    user_msg = (
        f"Theorem:\n{theorem_signature}\n\n"
        f"Tactics so far:\n{prefix_txt}\n\n"
        f"Current active goals:\n" + ("\n".join(active_goals) or "(none)") + "\n\n"
        f"Relevant premises:\n{premises_text}"
    )
    return system_msg, user_msg


class AnthropicLLMBackend:
    """Native Anthropic Messages API prover backend (`ANTHROPIC_API_KEY`)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        base_url: str = "https://api.anthropic.com/v1/messages",
        max_tokens: int = 1024,
        timeout_s: float = 60.0,
        input_usd_per_mtok: float = 3.0,
        output_usd_per_mtok: float = 15.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.input_usd_per_mtok = input_usd_per_mtok
        self.output_usd_per_mtok = output_usd_per_mtok

    def _call(self, system_msg: str, user_msg: str) -> Tuple[str, float]:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured for AnthropicLLMBackend.")
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0.1,
            "system": system_msg,
            "messages": [{"role": "user", "content": user_msg}],
        }
        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with _urlopen_smart(req, timeout=self.timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        blocks = data.get("content") or []
        text = "\n".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text")
        usage = data.get("usage") or {}
        in_tok = int(usage.get("input_tokens", 0))
        out_tok = int(usage.get("output_tokens", 0))
        cost = (in_tok * self.input_usd_per_mtok + out_tok * self.output_usd_per_mtok) / 1_000_000.0
        return text, cost if cost > 0 else 0.015

    def propose_tactic_proof(self, ctx: ProofPromptContext) -> Tuple[str, float]:
        sys_msg, user_msg = _build_full_proof_messages(ctx)
        raw, cost = self._call(sys_msg, user_msg)
        return _clean_tactic_response(raw), cost

    def propose_tactic_steps(
        self,
        theorem_signature: str,
        tactic_prefix: Sequence[str],
        active_goals: Sequence[str],
        premises_text: str,
        k: int = 4,
    ) -> Tuple[List[str], float]:
        sys_msg, user_msg = _build_tree_step_messages(theorem_signature, tactic_prefix, active_goals, premises_text, k=k)
        raw, cost = self._call(sys_msg, user_msg)
        return _parse_step_candidates(raw, max_k=k), cost


class OpenAILLMBackend:
    """Native OpenAI Chat Completions prover backend (`OPENAI_API_KEY` / `PCVH_LLM_API_KEY`)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4.1-mini",
        base_url: str = "https://api.openai.com/v1/chat/completions",
        timeout_s: float = 60.0,
        input_usd_per_mtok: float = 0.4,
        output_usd_per_mtok: float = 1.6,
    ) -> None:
        self.api_key = api_key or os.environ.get("PCVH_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.input_usd_per_mtok = input_usd_per_mtok
        self.output_usd_per_mtok = output_usd_per_mtok

    def _call(self, system_msg: str, user_msg: str) -> Tuple[str, float]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY / PCVH_LLM_API_KEY is not configured for OpenAILLMBackend.")
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
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
        with _urlopen_smart(req, timeout=self.timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = str(data["choices"][0]["message"]["content"])
        usage = data.get("usage") or {}
        in_tok = int(usage.get("prompt_tokens", 0))
        out_tok = int(usage.get("completion_tokens", 0))
        cost = (in_tok * self.input_usd_per_mtok + out_tok * self.output_usd_per_mtok) / 1_000_000.0
        return text, cost if cost > 0 else 0.005

    def propose_tactic_proof(self, ctx: ProofPromptContext) -> Tuple[str, float]:
        sys_msg, user_msg = _build_full_proof_messages(ctx)
        raw, cost = self._call(sys_msg, user_msg)
        return _clean_tactic_response(raw), cost

    def propose_tactic_steps(
        self,
        theorem_signature: str,
        tactic_prefix: Sequence[str],
        active_goals: Sequence[str],
        premises_text: str,
        k: int = 4,
    ) -> Tuple[List[str], float]:
        sys_msg, user_msg = _build_tree_step_messages(theorem_signature, tactic_prefix, active_goals, premises_text, k=k)
        raw, cost = self._call(sys_msg, user_msg)
        return _parse_step_candidates(raw, max_k=k), cost


class OllamaLLMBackend:
    """Local Ollama REST API prover backend (`OLLAMA_HOST`, zero API key, $0.00 cost)."""

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_s: float = 120.0,
    ) -> None:
        host = (base_url or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        self.base_url = host if host.endswith("/api/chat") else f"{host}/api/chat"
        self.model = model or os.environ.get("OLLAMA_MODEL") or "qwen2.5-coder:14b"
        self.timeout_s = timeout_s

    def _call(self, system_msg: str, user_msg: str) -> Tuple[str, float]:
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": 0.1},
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        }
        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _urlopen_smart(req, timeout=self.timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        msg = data.get("message") or {}
        text = str(msg.get("content", ""))
        return text, 0.0

    def propose_tactic_proof(self, ctx: ProofPromptContext) -> Tuple[str, float]:
        sys_msg, user_msg = _build_full_proof_messages(ctx)
        raw, cost = self._call(sys_msg, user_msg)
        return _clean_tactic_response(raw), cost

    def propose_tactic_steps(
        self,
        theorem_signature: str,
        tactic_prefix: Sequence[str],
        active_goals: Sequence[str],
        premises_text: str,
        k: int = 4,
    ) -> Tuple[List[str], float]:
        sys_msg, user_msg = _build_tree_step_messages(theorem_signature, tactic_prefix, active_goals, premises_text, k=k)
        raw, cost = self._call(sys_msg, user_msg)
        return _parse_step_candidates(raw, max_k=k), cost


@dataclass(frozen=True)
class ProviderStatus:
    provider: str
    configured: bool
    default_model: str
    detail: str


def describe_available_providers() -> List[Dict[str, object]]:
    """Report which LLM providers are currently configured via environment variables."""
    statuses = [
        ProviderStatus(
            provider="anthropic",
            configured=bool(os.environ.get("ANTHROPIC_API_KEY")),
            default_model=os.environ.get("PCVH_ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            detail="ANTHROPIC_API_KEY set" if os.environ.get("ANTHROPIC_API_KEY") else "Set ANTHROPIC_API_KEY",
        ),
        ProviderStatus(
            provider="openai",
            configured=bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("PCVH_LLM_API_KEY")),
            default_model=os.environ.get("PCVH_OPENAI_MODEL", "gpt-4.1-mini"),
            detail="OPENAI_API_KEY set" if (os.environ.get("OPENAI_API_KEY") or os.environ.get("PCVH_LLM_API_KEY")) else "Set OPENAI_API_KEY",
        ),
        ProviderStatus(
            provider="ollama",
            configured=bool(os.environ.get("OLLAMA_HOST")),
            default_model=os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:14b"),
            detail=f"OLLAMA_HOST={os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')}",
        ),
    ]
    return [
        {
            "provider": s.provider,
            "configured": s.configured,
            "default_model": s.default_model,
            "detail": s.detail,
        }
        for s in statuses
    ]


def create_llm_backend(
    provider: str = "auto",
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[LLMBackend]:
    """Instantiate a configured LLM backend (`anthropic`, `openai`, `ollama`, `auto`, or `none`)."""
    p = provider.lower().strip()
    if p in ("none", "off", "disabled"):
        return None
    if p == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            p = "anthropic"
        elif os.environ.get("OPENAI_API_KEY") or os.environ.get("PCVH_LLM_API_KEY"):
            p = "openai"
        elif os.environ.get("OLLAMA_HOST"):
            p = "ollama"
        else:
            return None

    if p == "anthropic":
        return AnthropicLLMBackend(
            api_key=api_key,
            model=model or os.environ.get("PCVH_ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            base_url=base_url or "https://api.anthropic.com/v1/messages",
        )
    if p == "openai":
        return OpenAILLMBackend(
            api_key=api_key,
            model=model or os.environ.get("PCVH_OPENAI_MODEL", "gpt-4.1-mini"),
            base_url=base_url or "https://api.openai.com/v1/chat/completions",
        )
    if p == "ollama":
        return OllamaLLMBackend(
            model=model,
            base_url=base_url,
        )
    raise ValueError(f"Unknown LLM provider '{provider}'. Expected one of: anthropic, openai, ollama, auto, none.")
