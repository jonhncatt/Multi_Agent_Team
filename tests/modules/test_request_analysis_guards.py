from __future__ import annotations

from typing import Any

from packages.office_modules.intent_support import request_likely_requires_tools
from packages.office_modules.request_analysis import looks_like_permission_gate_text


class _AgentStub:
    def _attachment_needs_tooling(self, meta: dict[str, Any]) -> bool:
        return bool(meta.get("needs_tooling"))

    def _attachment_is_inline_parseable(self, meta: dict[str, Any]) -> bool:
        return bool(meta.get("inline_parseable", not bool(meta.get("needs_tooling"))))

    def _looks_like_inline_document_payload(self, user_message: str) -> bool:
        return "```" in str(user_message or "")

    def _looks_like_write_or_edit_action(self, text: str) -> bool:
        lowered = str(text or "").lower()
        return any(marker in lowered for marker in ("修复", "更新", "升级", "patch", "fix", "update", "upgrade"))

    def _has_file_like_lookup_token(self, text: str) -> bool:
        lowered = str(text or "").lower()
        return any(marker in lowered for marker in (".py", ".ts", ".md", ".json", "repo"))


def test_permission_gate_detects_planner_plan_only_refusal() -> None:
    text = "抱歉，次任务目前不能直接读取仓库内容，因为planner的约束指出本轮只能输出计划，不能联网下载。"
    assert looks_like_permission_gate_text(text, request_requires_tools=True) is True


def test_permission_gate_detects_self_update_forbidden_refusal() -> None:
    text = "这是禁止能力，不能实现或设计任何形式的自我更新。"
    assert looks_like_permission_gate_text(text, request_requires_tools=True) is True


def test_permission_gate_detects_cannot_upgrade_module_refusal() -> None:
    text = "当前系统无法升级模块，但可以直接解决这个问题。"
    assert looks_like_permission_gate_text(text, request_requires_tools=True) is True


def test_request_likely_requires_tools_for_evolution_request() -> None:
    agent = _AgentStub()
    assert request_likely_requires_tools(
        agent,
        "对 planner 实现进化、自我修复和热插拔升级。",
        [],
        news_hints=("news", "新闻"),
    ) is True


def test_request_likely_requires_tools_for_github_repo_url() -> None:
    agent = _AgentStub()
    assert request_likely_requires_tools(
        agent,
        "读取 https://github.com/jonhncatt/Sequoia 里面所有内容。",
        [],
        news_hints=("news", "新闻"),
    ) is True


def test_request_likely_requires_tools_for_plain_upgrade_command() -> None:
    agent = _AgentStub()
    assert request_likely_requires_tools(
        agent,
        "你现在就去升级模块。",
        [],
        news_hints=("news", "新闻"),
    ) is True
