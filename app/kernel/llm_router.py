from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class LLMRouterDecision:
    target_agent: str
    reason: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMRouter:
    """Central LLM scheduler for routing tasks to independent agent plugins."""

    def __init__(self, *, default_agent: str = "worker_agent") -> None:
        self.default_agent = str(default_agent or "worker_agent").strip() or "worker_agent"

    def route(
        self,
        message: str,
        *,
        candidate_agents: list[str] | tuple[str, ...] | None = None,
        context: dict[str, Any] | None = None,
    ) -> LLMRouterDecision:
        text = str(message or "").strip().lower()
        candidates = [str(item or "").strip() for item in (candidate_agents or []) if str(item or "").strip()]
        if not candidates:
            candidates = [self.default_agent]

        preferred = self.default_agent
        reason = "default route"

        if any(token in text for token in ("总结", "summary", "summar")) and "summarizer_agent" in candidates:
            preferred = "summarizer_agent"
            reason = "summary-intent"
        elif any(token in text for token in ("查", "搜索", "search", "research", "检索")) and "researcher_agent" in candidates:
            preferred = "researcher_agent"
            reason = "research-intent"
        elif any(token in text for token in ("修复", "fix", "bug")) and "fixer_agent" in candidates:
            preferred = "fixer_agent"
            reason = "fix-intent"

        if preferred not in candidates:
            preferred = candidates[0]
            reason = "fallback-first-candidate"

        return LLMRouterDecision(
            target_agent=preferred,
            reason=reason,
            confidence=0.6 if preferred == self.default_agent else 0.72,
            metadata={
                "candidate_count": len(candidates),
                "message_preview": text[:120],
                "context_keys": sorted((context or {}).keys()),
            },
        )
