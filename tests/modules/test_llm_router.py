from __future__ import annotations

from app.kernel.llm_router import LLMRouter, LLMRouterDecision


def test_llm_router_uses_default_agent_without_candidates() -> None:
    router = LLMRouter()
    decision = router.route("你好")

    assert isinstance(decision, LLMRouterDecision)
    assert decision.target_agent == "worker_agent"
    assert decision.reason == "default route"
    assert decision.confidence == 0.6


def test_llm_router_prefers_summarizer_for_summary_intent() -> None:
    router = LLMRouter()
    decision = router.route(
        "请帮我总结这段内容",
        candidate_agents=["worker_agent", "summarizer_agent"],
    )

    assert decision.target_agent == "summarizer_agent"
    assert decision.reason == "summary-intent"


def test_llm_router_prefers_researcher_for_search_intent() -> None:
    router = LLMRouter()
    decision = router.route(
        "请帮我搜索最新资料",
        candidate_agents=["worker_agent", "researcher_agent"],
    )

    assert decision.target_agent == "researcher_agent"
    assert decision.reason == "research-intent"


def test_llm_router_falls_back_to_first_candidate_when_preferred_missing() -> None:
    router = LLMRouter(default_agent="worker_agent")
    decision = router.route(
        "请帮我修复这个 bug",
        candidate_agents=["reviewer_agent", "critic_agent"],
    )

    assert decision.target_agent == "reviewer_agent"
    assert decision.reason == "fallback-first-candidate"


def test_llm_router_metadata_reports_context_keys() -> None:
    router = LLMRouter()
    decision = router.route(
        "继续",
        candidate_agents=["worker_agent"],
        context={"project_id": "demo", "cwd": "/tmp/demo"},
    )

    assert decision.metadata["candidate_count"] == 1
    assert decision.metadata["context_keys"] == ["cwd", "project_id"]
    assert str(decision.metadata["message_preview"]) == "继续"
