from __future__ import annotations

import pytest

from tests.router.support import run_pipeline


@pytest.mark.parametrize(
    ("message", "attachments", "enable_tools", "expected_intent", "expected_policy"),
    [
        (
            "请整体解释这个附件",
            [{"inline_parseable": True, "needs_tooling": False}],
            True,
            "understanding",
            "attachment_holistic_understanding_with_tools",
        ),
        (
            "请给我这个结论的出处和依据",
            [],
            True,
            "evidence",
            "evidence_full_pipeline",
        ),
        (
            "today AI news with sources",
            [],
            True,
            "web",
            "web_research_full_pipeline",
        ),
        (
            "读取 https://github.com/jonhncatt/Sequoia 里面所有内容",
            [],
            True,
            "web",
            "web_research_full_pipeline",
        ),
        (
            "你现在就去升级模块，走 shadow self-upgrade。",
            [],
            True,
            "code_lookup",
            "code_lookup_with_tools",
        ),
        (
            "Look up the repo function that handles retries",
            [],
            True,
            "code_lookup",
            "code_lookup_with_tools",
        ),
        (
            "请写成一个 Python 脚本，把列表去重并保持顺序",
            [],
            False,
            "generation",
            "direct_generation",
        ),
    ],
)
def test_single_turn_intent_routes(
    message: str,
    attachments: list[dict[str, object]],
    enable_tools: bool,
    expected_intent: str,
    expected_policy: str,
) -> None:
    result = run_pipeline(
        message=message,
        attachments=attachments,
        enable_tools=enable_tools,
    )
    decision = result["decision"]
    route = result["route"]
    trace = result["trace"]

    assert decision.top_intent == expected_intent
    assert route["execution_policy"] == expected_policy
    assert trace.top_intent == expected_intent
    assert trace.chosen_execution_policy == expected_policy
    assert trace.margin >= 0.0
    assert trace.decision_source in {"rules", "llm"}
