from __future__ import annotations

import json
from typing import Any

from app.tool_trace_summary import safe_error_message, safe_preview


_TEXT_PREVIEW_LIMIT = 1000
_ARGS_PREVIEW_LIMIT = 2000
_TOOL_NAME_PREVIEW_LIMIT = 12


def build_request_summary(
    *,
    backend: str,
    provider: str,
    model: str,
    streaming: bool | None,
    api_path: str,
    messages: list[Any] | None = None,
    max_output_tokens: int | None = None,
    temperature: float | None = None,
    tools_available_count: int | None = None,
    tools_exposed: bool | None = None,
    tool_choice: str | None = None,
    tool_count_exposed: int | None = None,
) -> dict[str, Any]:
    try:
        roles = _message_role_counts(messages or [])
        exposed_count = max(0, int(tool_count_exposed or 0))
        available_count = max(exposed_count, int(tools_available_count or 0))
        exposed_flag = bool(tools_exposed) if tools_exposed is not None else bool(exposed_count)
        normalized_tool_choice = str(tool_choice or ("auto" if exposed_flag else "none")).strip() or "none"
        return {
            "backend": str(backend or "").strip() or "unknown",
            "provider": str(provider or "").strip() or "unknown",
            "model": str(model or "").strip(),
            "streaming": bool(streaming) if streaming is not None else False,
            "api_path": str(api_path or "").strip() or "unknown",
            "message_count": sum(roles.values()),
            "system_message_count": roles["system"],
            "user_message_count": roles["user"],
            "assistant_message_count": roles["assistant"],
            "tool_message_count": roles["tool"],
            "max_output_tokens": int(max_output_tokens or 0) or None,
            "temperature": temperature if temperature is None else float(temperature),
            "tools_available_count": available_count,
            "tools_exposed": exposed_flag,
            "tool_choice": normalized_tool_choice,
            "tool_count_exposed": exposed_count,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"diagnostics_error": safe_error_message(exc)}


def build_runtime_guess_summary(runtime_guess: dict[str, Any] | None) -> dict[str, Any]:
    try:
        guess = dict(runtime_guess or {})
        if not guess:
            return {"source": "missing"}
        return {
            "source": str(guess.get("source") or "runtime_guess"),
            "task_type": str(guess.get("task_type") or "standard"),
            "route_task_type": str(guess.get("route_task_type") or ""),
            "primary_intent": str(guess.get("primary_intent") or "standard"),
            "execution_policy": str(guess.get("execution_policy") or ""),
            "output_mode": str(guess.get("output_mode") or "direct_answer"),
            "prefer_change_summary": bool(guess.get("prefer_change_summary")),
            "summary_reason": str(guess.get("summary_reason") or ""),
            "current_goal_hint": str(guess.get("current_goal_hint") or ""),
            "next_action_hint": str(guess.get("next_action_hint") or ""),
            "current_turn_followup_type": str(guess.get("current_turn_followup_type") or ""),
            "current_turn_goal_source": str(guess.get("current_turn_goal_source") or ""),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"source": "error", "diagnostics_error": safe_error_message(exc)}


def build_proposal_parse_summary(
    high_level_proposal: dict[str, Any] | None,
    proposal_diagnostics: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        proposal = dict(high_level_proposal or {})
        diagnostics = dict(proposal_diagnostics or {})
        schema_validation = dict(diagnostics.get("schema_validation") or {})
        block_status = str(diagnostics.get("status") or "").strip().lower()
        proposal_source = str(proposal.get("source") or ("missing" if not proposal else "unknown")).strip() or "unknown"
        block_found = block_status not in {"", "missing"}
        block_valid_json = block_status == "parsed"
        errors: list[str] = []
        for item in list(diagnostics.get("errors") or []):
            text = str(item or "").strip()
            if text:
                errors.append(text)
        for item in list(schema_validation.get("errors") or []):
            text = str(item or "").strip()
            if text and text not in errors:
                errors.append(text)
        return {
            "proposal_source": proposal_source,
            "proposal_block_found": block_found,
            "proposal_block_valid_json": block_valid_json,
            "proposal_schema_status": str(schema_validation.get("status") or diagnostics.get("status") or "missing"),
            "intent": str(proposal.get("intent") or ""),
            "task_type": str(proposal.get("task_type") or "standard"),
            "current_goal": str(proposal.get("current_goal") or ""),
            "expects_tools": bool(proposal.get("expects_tools")),
            "response_mode": str(proposal.get("response_mode") or "direct_answer"),
            "user_stage": str(proposal.get("user_stage") or ""),
            "summary": str(proposal.get("summary") or ""),
            "next_step_hint": str(proposal.get("next_step_hint") or ""),
            "change_summary_requested": bool(proposal.get("change_summary_requested")),
            "raw_proposal_chars": int(diagnostics.get("raw_proposal_chars") or 0),
            "raw_proposal_preview": safe_preview(diagnostics.get("raw_proposal_preview") or "", limit=_TEXT_PREVIEW_LIMIT),
            "errors": errors[:16],
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"proposal_source": "error", "diagnostics_error": safe_error_message(exc)}


def build_tool_gating_summary(
    *,
    runtime_guess: dict[str, Any] | None,
    high_level_proposal: dict[str, Any] | None,
    runtime_contract: dict[str, Any] | Any | None,
    explicit_tool_request: bool | None,
    attachment_requires_tooling: bool | None,
    workspace_action_requested: bool | None,
    network_requested: bool | None,
    tools_should_be_exposed: bool | None,
    actual_tools_exposed: bool | None,
    tool_choice: str | None,
    exposed_tool_names: list[str] | None,
    tool_count_exposed: int | None = None,
) -> dict[str, Any]:
    try:
        guess = dict(runtime_guess or {})
        proposal = dict(high_level_proposal or {})
        contract = _as_payload(runtime_contract)
        runtime_output_mode = str(guess.get("output_mode") or "direct_answer")
        proposal_response_mode = str(proposal.get("response_mode") or runtime_output_mode or "direct_answer")
        proposal_expects_tools = bool(proposal.get("expects_tools"))
        explicit = bool(explicit_tool_request)
        attachment_required = bool(attachment_requires_tooling)
        workspace_requested = bool(workspace_action_requested)
        network = bool(network_requested)
        should_expose = bool(tools_should_be_exposed)
        actual_exposed = bool(actual_tools_exposed) if actual_tools_exposed is not None else None
        tool_names = [str(item or "").strip() for item in list(exposed_tool_names or []) if str(item or "").strip()]
        preview = tool_names[:_TOOL_NAME_PREVIEW_LIMIT]
        gate_expected = (
            runtime_output_mode == "direct_answer"
            and not explicit
            and not attachment_required
            and not workspace_requested
            and not network
        )
        direct_answer_gate_applied = gate_expected and actual_exposed is False
        reason = _tool_gating_reason(
            runtime_output_mode=runtime_output_mode,
            proposal_response_mode=proposal_response_mode,
            proposal_expects_tools=proposal_expects_tools,
            explicit_tool_request=explicit,
            attachment_requires_tooling=attachment_required,
            workspace_action_requested=workspace_requested,
            network_requested=network,
            tools_should_be_exposed=should_expose,
            actual_tools_exposed=actual_exposed,
        )
        return {
            "runtime_output_mode": runtime_output_mode,
            "proposal_response_mode": proposal_response_mode,
            "proposal_expects_tools": proposal_expects_tools,
            "explicit_tool_request": explicit,
            "attachment_requires_tooling": attachment_required,
            "workspace_action_requested": workspace_requested,
            "network_requested": network,
            "runtime_contract_tools_available": bool(contract.get("tools_available")),
            "direct_answer_gate_applied": direct_answer_gate_applied,
            "tools_should_be_exposed": should_expose,
            "actual_tools_exposed": actual_exposed,
            "tool_choice": str(tool_choice or ("auto" if actual_exposed else "none")).strip() or "none",
            "tool_count_exposed": max(0, int(tool_count_exposed if tool_count_exposed is not None else len(tool_names))),
            "tool_names_preview": preview,
            "tool_names_truncated": len(tool_names) > len(preview),
            "decision_source": "runtime_gate",
            "reason": reason,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"decision_source": "error", "diagnostics_error": safe_error_message(exc)}


def build_assistant_response_summary_from_message(message: Any) -> dict[str, Any]:
    try:
        tool_calls = list(getattr(message, "tool_calls", None) or [])
        response_metadata = dict(getattr(message, "response_metadata", None) or {})
        usage_metadata = dict(getattr(message, "usage_metadata", None) or {})
        content = _content_to_text(getattr(message, "content", ""))
        usage = dict(response_metadata.get("token_usage") or usage_metadata or {})
        if int(usage.get("total_tokens", 0) or 0) <= 0:
            usage["total_tokens"] = int(usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0) or 0) + int(
                usage.get("output_tokens", 0) or usage.get("completion_tokens", 0) or 0
            )
        summary = {
            "assistant_content_chars": len(content),
            "assistant_content_preview": safe_preview(content, limit=_TEXT_PREVIEW_LIMIT) or "",
            "assistant_tool_calls_count": len(tool_calls),
            "finish_reason": str(response_metadata.get("finish_reason") or ""),
            "response_id": str(response_metadata.get("response_id") or ""),
            "usage": {
                "input_tokens": int(usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0) or 0),
                "output_tokens": int(usage.get("output_tokens", 0) or usage.get("completion_tokens", 0) or 0),
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
            },
            "stream_diagnostics": dict(response_metadata.get("stream_diagnostics") or {}),
            "tool_calls": [_tool_call_summary(index, item) for index, item in enumerate(tool_calls)],
        }
        return summary
    except Exception as exc:  # pragma: no cover - defensive
        return {"diagnostics_error": safe_error_message(exc)}


def build_model_runtime_analysis(
    *,
    request_summary: dict[str, Any] | None,
    runtime_guess: dict[str, Any] | None,
    high_level_proposal: dict[str, Any] | None,
    proposal_diagnostics: dict[str, Any] | None,
    runtime_contract: dict[str, Any] | Any | None,
    explicit_tool_request: bool | None,
    attachment_requires_tooling: bool | None,
    workspace_action_requested: bool | None,
    network_requested: bool | None,
    tools_should_be_exposed: bool | None,
    actual_tools_exposed: bool | None,
    tool_choice: str | None,
    exposed_tool_names: list[str] | None,
    assistant_message: Any | None = None,
    assistant_response_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        request = dict(request_summary or {})
        runtime = build_runtime_guess_summary(runtime_guess)
        proposal = build_proposal_parse_summary(high_level_proposal, proposal_diagnostics)
        actual_exposed = actual_tools_exposed
        if actual_exposed is None and "tools_exposed" in request:
            actual_exposed = bool(request.get("tools_exposed"))
        actual_tool_choice = tool_choice or str(request.get("tool_choice") or "")
        tool_count_exposed = int(request.get("tool_count_exposed", 0) or 0)
        tool_gating = build_tool_gating_summary(
            runtime_guess=runtime_guess,
            high_level_proposal=high_level_proposal,
            runtime_contract=runtime_contract,
            explicit_tool_request=explicit_tool_request,
            attachment_requires_tooling=attachment_requires_tooling,
            workspace_action_requested=workspace_action_requested,
            network_requested=network_requested,
            tools_should_be_exposed=tools_should_be_exposed,
            actual_tools_exposed=actual_exposed,
            tool_choice=actual_tool_choice,
            exposed_tool_names=exposed_tool_names,
            tool_count_exposed=tool_count_exposed,
        )
        assistant = dict(assistant_response_summary or {})
        if not assistant and assistant_message is not None:
            assistant = build_assistant_response_summary_from_message(assistant_message)
        warnings = _collect_diagnostic_warnings(
            proposal_parse=proposal,
            tool_gating=tool_gating,
            assistant_response_summary=assistant,
        )
        return {
            "request_summary": request,
            "runtime_guess": runtime,
            "proposal_parse": proposal,
            "tool_gating": tool_gating,
            "assistant_response_summary": assistant,
            "diagnostic_warnings": warnings,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"diagnostics_error": safe_error_message(exc)}


def _message_role_counts(messages: list[Any]) -> dict[str, int]:
    counts = {"system": 0, "user": 0, "assistant": 0, "tool": 0}
    for message in list(messages or []):
        role = ""
        if isinstance(message, dict):
            role = str(message.get("role") or message.get("type") or "").strip().lower()
        else:
            role = str(getattr(message, "role", "") or getattr(message, "type", "")).strip().lower()
        if role in {"human", "user"}:
            counts["user"] += 1
        elif role in {"ai", "assistant"}:
            counts["assistant"] += 1
        elif role == "tool":
            counts["tool"] += 1
        else:
            counts["system"] += 1 if role == "system" else 0
    return counts


def _as_payload(runtime_contract: dict[str, Any] | Any | None) -> dict[str, Any]:
    if isinstance(runtime_contract, dict):
        return dict(runtime_contract)
    if runtime_contract is None:
        return {}
    payload = getattr(runtime_contract, "as_payload", None)
    if callable(payload):
        try:
            result = payload()
            return dict(result or {}) if isinstance(result, dict) else {}
        except Exception:
            return {}
    return {
        "tools_available": bool(getattr(runtime_contract, "tools_available", False)),
        "tool_policy": str(getattr(runtime_contract, "tool_policy", "") or ""),
    }


def _tool_gating_reason(
    *,
    runtime_output_mode: str,
    proposal_response_mode: str,
    proposal_expects_tools: bool,
    explicit_tool_request: bool,
    attachment_requires_tooling: bool,
    workspace_action_requested: bool,
    network_requested: bool,
    tools_should_be_exposed: bool,
    actual_tools_exposed: bool | None,
) -> str:
    if runtime_output_mode == "direct_answer" and actual_tools_exposed:
        return "BUG: direct_answer predicted but tools were exposed"
    if explicit_tool_request or attachment_requires_tooling or workspace_action_requested or network_requested:
        return "tool exposure allowed because the request explicitly indicates tool or workspace/network work"
    if tools_should_be_exposed:
        return "tool exposure allowed by runtime gate"
    if runtime_output_mode == "direct_answer" and proposal_response_mode == "direct_answer":
        if proposal_expects_tools:
            return "runtime output_mode is direct_answer, but the model proposal still expects tools"
        return "runtime output_mode is direct_answer and no explicit tool request was detected"
    return "tool exposure decision followed the current runtime and proposal state"


def _tool_call_summary(index: int, tool_call: Any) -> dict[str, Any]:
    item = dict(tool_call or {}) if isinstance(tool_call, dict) else {}
    raw_args = item.get("raw_args")
    parsed_args = item.get("args")
    args_type, args_preview, raw_args_chars, raw_args_preview, parse_status = _analyze_tool_call_args(
        raw_args=raw_args,
        parsed_args=parsed_args,
    )
    return {
        "index": int(index),
        "id_present": bool(str(item.get("id") or "").strip()),
        "name": str(item.get("name") or ""),
        "args_type": args_type,
        "args_preview": args_preview,
        "raw_args_chars": raw_args_chars,
        "raw_args_preview": raw_args_preview,
        "args_parse_status": parse_status,
    }


def _analyze_tool_call_args(
    *,
    raw_args: Any,
    parsed_args: Any,
) -> tuple[str, Any, int, Any, str]:
    raw_preview = safe_preview(raw_args, limit=_ARGS_PREVIEW_LIMIT)
    if isinstance(raw_args, str):
        raw_text = raw_args
        raw_chars = len(raw_text)
        stripped = raw_text.strip()
        if not stripped:
            if isinstance(parsed_args, dict):
                return "dict", safe_preview(parsed_args, limit=_ARGS_PREVIEW_LIMIT), raw_chars, raw_preview, (
                    "empty_object" if not parsed_args else "valid_object"
                )
            return "missing", None, raw_chars, raw_preview, "missing"
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            return "str", None, raw_chars, raw_preview, "invalid_json"
        if isinstance(decoded, dict):
            status = "empty_object" if not decoded else "valid_object"
            return "dict", safe_preview(decoded, limit=_ARGS_PREVIEW_LIMIT), raw_chars, raw_preview, status
        return type(decoded).__name__, None, raw_chars, raw_preview, "not_object"

    if isinstance(raw_args, dict):
        status = "empty_object" if not raw_args else "valid_object"
        return "dict", safe_preview(raw_args, limit=_ARGS_PREVIEW_LIMIT), len(json.dumps(raw_args, ensure_ascii=False)), raw_preview, status

    if isinstance(parsed_args, dict):
        status = "empty_object" if not parsed_args else "valid_object"
        return "dict", safe_preview(parsed_args, limit=_ARGS_PREVIEW_LIMIT), 0, raw_preview, status

    if raw_args is None and parsed_args in (None, ""):
        return "missing", None, 0, raw_preview, "missing"

    return type(raw_args).__name__ if raw_args is not None else "unknown", None, 0, raw_preview, "unknown"


def _collect_diagnostic_warnings(
    *,
    proposal_parse: dict[str, Any],
    tool_gating: dict[str, Any],
    assistant_response_summary: dict[str, Any],
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []

    def add(code: str, message: str, *, severity: str = "warning") -> None:
        if any(str(item.get("code") or "") == code for item in warnings):
            return
        warnings.append({"code": code, "severity": severity, "message": message})

    if (
        str(proposal_parse.get("response_mode") or "") == "direct_answer"
        and bool(proposal_parse.get("expects_tools"))
    ):
        add(
            "direct_answer_proposal_expects_tools",
            "direct_answer predicted, but proposal expects_tools=true",
        )

    if (
        str(tool_gating.get("runtime_output_mode") or "") == "direct_answer"
        and tool_gating.get("actual_tools_exposed") is True
    ):
        add(
            "direct_answer_tools_exposed",
            "direct_answer predicted, but tools were exposed",
        )
        if str(tool_gating.get("tool_choice") or "") == "auto":
            add(
                "simple_direct_answer_tool_choice_auto",
                "tools were exposed while tool_choice=auto for a simple direct answer",
            )

    if (
        str(tool_gating.get("runtime_output_mode") or "") == "direct_answer"
        and int(assistant_response_summary.get("assistant_tool_calls_count") or 0) > 0
    ):
        add(
            "assistant_tool_calls_direct_answer",
            "assistant returned tool calls although runtime_output_mode=direct_answer",
        )

    if not bool(proposal_parse.get("proposal_block_found")) and str(proposal_parse.get("proposal_source") or "") == "runtime_fallback":
        add(
            "proposal_block_missing_runtime_fallback",
            "proposal block missing; runtime fallback was used",
        )

    for item in list(assistant_response_summary.get("tool_calls") or []):
        status = str((item or {}).get("args_parse_status") or "")
        if status == "invalid_json":
            add("tool_call_arguments_invalid_json", "tool call arguments JSON parse failed")
        elif status == "not_object":
            add("tool_call_arguments_not_object", "tool call arguments were not a JSON object")

    return warnings


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if text is not None:
                    parts.append(str(text))
                    continue
        return "".join(parts)
    return str(content or "")
