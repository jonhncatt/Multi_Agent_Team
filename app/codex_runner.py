from __future__ import annotations

import json
import time
from typing import Any

from openai import OpenAI

from app.openai_auth import OpenAIAuthManager


def build_codex_input_payload(messages: list[Any]) -> tuple[str, list[dict[str, Any]]]:
    return _messages_to_codex_input(messages)


class CodexResponsesRunner:
    def __init__(
        self,
        *,
        auth_manager: OpenAIAuthManager,
        model: str,
        max_output_tokens: int,
        temperature: float | None,
        ai_message_cls: Any,
        tools: list[Any] | None = None,
    ) -> None:
        self._auth_manager = auth_manager
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._AIMessage = ai_message_cls
        self._tools = list(tools or [])

    def bind_tools(self, tools: list[Any]) -> "CodexResponsesRunner":
        return CodexResponsesRunner(
            auth_manager=self._auth_manager,
            model=self._model,
            max_output_tokens=self._max_output_tokens,
            temperature=self._temperature,
            ai_message_cls=self._AIMessage,
            tools=tools,
        )

    def invoke(self, messages: list[Any]) -> Any:
        try:
            return self._invoke_once(messages, allow_refresh=True)
        except Exception as exc:
            text = str(exc).lower()
            if "401" not in text and "unauthorized" not in text:
                raise
        self._auth_manager.refresh_codex_auth(force=True)
        return self._invoke_once(messages, allow_refresh=False)

    def invoke_with_events(
        self,
        messages: list[Any],
        *,
        event_cb: Any | None = None,
    ) -> Any:
        try:
            return self._invoke_once(messages, allow_refresh=True, event_cb=event_cb)
        except Exception as exc:
            text = str(exc).lower()
            if "401" not in text and "unauthorized" not in text:
                raise
        self._auth_manager.refresh_codex_auth(force=True)
        return self._invoke_once(messages, allow_refresh=False, event_cb=event_cb)

    def _invoke_once(
        self,
        messages: list[Any],
        *,
        allow_refresh: bool,
        event_cb: Any | None = None,
    ) -> Any:
        auth = self._auth_manager.require(allow_refresh=allow_refresh)
        if auth.mode != "codex_auth":
            raise RuntimeError(f"Codex runner requires codex_auth, got {auth.mode}.")
        if not str(auth.access_token or "").strip() or not str(auth.account_id or "").strip():
            raise RuntimeError("Codex auth requires access_token and account_id.")

        instructions, input_items = _messages_to_codex_input(messages)
        client = OpenAI(
            api_key=str(auth.access_token),
            base_url=str(auth.chatgpt_base_url),
            default_headers={"chatgpt-account-id": str(auth.account_id)},
        )
        request_kwargs: dict[str, Any] = {
            "model": self._model,
            "instructions": instructions or "You are a helpful assistant.",
            "input": input_items or [
                {"role": "user", "content": [{"type": "input_text", "text": "Continue."}]}
            ],
            "stream": True,
            "store": False,
        }
        if self._temperature is not None:
            request_kwargs["temperature"] = float(self._temperature)
        tool_payloads = _langchain_tools_to_codex_tools(self._tools)
        if tool_payloads:
            request_kwargs["tools"] = tool_payloads

        stream = client.responses.create(**request_kwargs)
        final_response = None
        final_error = None
        stream_diagnostics: dict[str, Any] = {
            "provider": "codex_auth",
            "event_count": 0,
            "text_delta_count": 0,
            "text_chars": 0,
            "first_event_at": 0.0,
            "first_text_delta_at": 0.0,
            "last_text_delta_at": 0.0,
            "completed_at": 0.0,
        }
        for event in stream:
            event_type = str(getattr(event, "type", "") or "")
            now = time.time()
            stream_diagnostics["event_count"] = int(stream_diagnostics.get("event_count") or 0) + 1
            if not stream_diagnostics["first_event_at"]:
                stream_diagnostics["first_event_at"] = now
            if event_cb is not None and event_type == "response.output_text.delta":
                delta = _coerce_event_text_delta(event)
                if delta:
                    stream_diagnostics["text_delta_count"] = int(stream_diagnostics.get("text_delta_count") or 0) + 1
                    stream_diagnostics["text_chars"] = int(stream_diagnostics.get("text_chars") or 0) + len(delta)
                    if not stream_diagnostics["first_text_delta_at"]:
                        stream_diagnostics["first_text_delta_at"] = now
                    stream_diagnostics["last_text_delta_at"] = now
                    event_cb(
                        {
                            "type": "response.output_text.delta",
                            "delta": delta,
                            "timestamp": now,
                            "model": self._model,
                            "provider": "codex_auth",
                        }
                    )
            if event_type == "response.completed":
                final_response = getattr(event, "response", None)
                stream_diagnostics["completed_at"] = now
                if event_cb is not None:
                    event_cb(
                        {
                            "type": "response.completed",
                            "timestamp": now,
                            "model": self._model,
                            "provider": "codex_auth",
                            "diagnostics": dict(stream_diagnostics),
                        }
                    )
            elif event_type == "response.failed":
                final_error = getattr(getattr(event, "response", None), "error", None) or getattr(event, "error", None)

        if final_error is not None:
            raise RuntimeError(f"Codex response failed: {final_error}")
        if final_response is None:
            raise RuntimeError("Codex response stream completed without a final response.")
        return _response_to_ai_message(self._AIMessage, final_response, stream_diagnostics=stream_diagnostics)


def _messages_to_codex_input(messages: list[Any]) -> tuple[str, list[dict[str, Any]]]:
    instructions_parts: list[str] = []
    input_items: list[dict[str, Any]] = []

    for message in messages:
        message_type = str(getattr(message, "type", "") or "").strip().lower()
        content_text = _content_to_text(getattr(message, "content", ""))

        if message_type == "system":
            if content_text:
                instructions_parts.append(content_text)
            continue

        if message_type == "human":
            input_items.append(
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": content_text or ""}],
                }
            )
            continue

        if message_type == "ai":
            if content_text:
                input_items.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content_text}],
                    }
                )
            for call in getattr(message, "tool_calls", None) or []:
                args = call.get("args") if isinstance(call, dict) else {}
                serialized_args = args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)
                call_id = str((call.get("id") if isinstance(call, dict) else None) or "").strip() or "call_missing"
                name = str((call.get("name") if isinstance(call, dict) else None) or "").strip()
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": name,
                        "arguments": serialized_args,
                    }
                )
            continue

        if message_type == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(getattr(message, "tool_call_id", "") or "tool_missing"),
                    "output": content_text,
                }
            )
            continue

    instructions = "\n\n".join(part for part in instructions_parts if part).strip()
    return instructions, input_items


def _langchain_tools_to_codex_tools(tools: list[Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for tool in tools:
        name = str(getattr(tool, "name", "") or "").strip()
        if not name:
            continue
        description = str(getattr(tool, "description", "") or "").strip()
        schema = _tool_schema(tool)
        payloads.append(
            {
                "type": "function",
                "name": name,
                "description": description,
                "parameters": schema,
                "strict": False,
            }
        )
    return payloads


def _tool_schema(tool: Any) -> dict[str, Any]:
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is not None and hasattr(args_schema, "model_json_schema"):
        try:
            schema = args_schema.model_json_schema()
            if isinstance(schema, dict) and schema:
                normalized = dict(schema)
                normalized.setdefault("type", "object")
                normalized.setdefault("properties", {})
                normalized.setdefault("required", [])
                normalized["additionalProperties"] = False
                return normalized
        except Exception:
            pass
    return {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


def _response_to_ai_message(
    ai_message_cls: Any,
    response: Any,
    *,
    stream_diagnostics: dict[str, Any] | None = None,
) -> Any:
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for item in getattr(response, "output", None) or []:
        item_type = str(getattr(item, "type", "") or "").strip().lower()
        if item_type == "message":
            for block in getattr(item, "content", None) or []:
                block_type = str(getattr(block, "type", "") or "").strip().lower()
                if block_type in {"output_text", "text"}:
                    block_text = str(getattr(block, "text", "") or "")
                    if block_text:
                        text_parts.append(block_text)
            continue
        if item_type == "function_call":
            raw_arguments = str(getattr(item, "arguments", "") or "{}")
            try:
                parsed_args = json.loads(raw_arguments) if raw_arguments.strip() else {}
            except Exception:
                parsed_args = {}
            tool_calls.append(
                {
                    "name": str(getattr(item, "name", "") or ""),
                    "args": parsed_args,
                    "id": str(getattr(item, "call_id", "") or getattr(item, "id", "") or "call_missing"),
                    "type": "tool_call",
                }
            )

    usage = getattr(response, "usage", None)
    token_usage = {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }
    text = "\n".join(part for part in text_parts if part).strip()
    return ai_message_cls(
        content=text,
        tool_calls=tool_calls,
        usage_metadata=token_usage,
        response_metadata={
            "token_usage": token_usage,
            "provider": "codex_auth",
            "response_id": str(getattr(response, "id", "") or ""),
            "model": str(getattr(response, "model", "") or ""),
            "stream_diagnostics": dict(stream_diagnostics or {}),
        },
    )


def _coerce_event_text_delta(event: Any) -> str:
    direct = getattr(event, "delta", None)
    if isinstance(direct, str):
        return direct
    if direct is not None and hasattr(direct, "text"):
        return str(getattr(direct, "text", "") or "")
    item = getattr(event, "item", None)
    if item is not None and hasattr(item, "text"):
        return str(getattr(item, "text", "") or "")
    return ""


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")

    out: list[str] = []
    for item in content:
        if isinstance(item, str):
            out.append(item)
            continue
        if not isinstance(item, dict):
            out.append(str(item))
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type in {"text", "output_text", "input_text"}:
            out.append(str(item.get("text") or ""))
            continue
        if "text" in item:
            out.append(str(item.get("text") or ""))
    return "\n".join(part for part in out if part)
