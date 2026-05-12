from __future__ import annotations

import json
import time
from typing import Any

import httpx
from openai import OpenAI

try:
    from openai import APIConnectionError, APIError, APITimeoutError, AuthenticationError, BadRequestError, RateLimitError
except Exception:  # pragma: no cover - fallback for older SDKs
    class _OpenAIError(Exception):
        pass

    APIConnectionError = _OpenAIError
    APIError = _OpenAIError
    APITimeoutError = _OpenAIError
    AuthenticationError = _OpenAIError
    BadRequestError = _OpenAIError
    RateLimitError = _OpenAIError

from app.model_runtime_diagnostics import (
    build_assistant_response_summary_from_message,
    build_request_summary,
)
from app.openai_auth import OpenAIAuthManager

from .message_codec import encode_messages
from .tool_schema import build_openai_tools
from .types import AIMessage, NativeLLMResponse, NativeLLMToolCall

_PROVIDER = "openai_native"


class _StreamingAttemptError(Exception):
    def __init__(self, exc: Exception, *, stream_started: bool, include_usage: bool) -> None:
        super().__init__(str(exc))
        self.original = exc
        self.stream_started = bool(stream_started)
        self.include_usage = bool(include_usage)


class OpenAINativeLLMAdapter:
    def __init__(
        self,
        *,
        auth_manager: OpenAIAuthManager | None = None,
        api_key: str | None = None,
        base_url: str | None,
        model: str,
        provider: str | None = None,
        max_output_tokens: int,
        temperature: float | None,
        ai_message_cls: Any = AIMessage,
        tools: list[Any] | None = None,
        timeout: float | None = None,
        extra_headers: dict[str, str] | None = None,
        verify: str | bool | None = None,
    ) -> None:
        self._auth_manager = auth_manager
        self._api_key = str(api_key or "").strip() or None
        self._base_url = str(base_url or "").strip() or None
        self._model = model
        self._provider = str(provider or "").strip() or _PROVIDER
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._AIMessage = ai_message_cls
        self._tools = list(tools or [])
        self._timeout = timeout
        self._extra_headers = dict(extra_headers or {})
        self._verify = verify

    def bind_tools(self, tools: list[Any]) -> "OpenAINativeLLMAdapter":
        return OpenAINativeLLMAdapter(
            auth_manager=self._auth_manager,
            api_key=self._api_key,
            base_url=self._base_url,
            model=self._model,
            provider=self._provider,
            max_output_tokens=self._max_output_tokens,
            temperature=self._temperature,
            ai_message_cls=self._AIMessage,
            tools=tools,
            timeout=self._timeout,
            extra_headers=self._extra_headers,
            verify=self._verify,
        )

    def invoke(self, messages: list[Any]) -> Any:
        return self._invoke_once(messages, allow_refresh=True)

    def invoke_with_events(
        self,
        messages: list[Any],
        *,
        event_cb: Any | None = None,
    ) -> Any:
        try:
            return self._invoke_streaming_attempt(
                messages,
                allow_refresh=True,
                event_cb=event_cb,
                include_usage=True,
            )
        except _StreamingAttemptError as exc:
            if not exc.stream_started and exc.include_usage and _looks_like_stream_usage_error(exc.original):
                try:
                    return self._invoke_streaming_attempt(
                        messages,
                        allow_refresh=True,
                        event_cb=event_cb,
                        include_usage=False,
                    )
                except _StreamingAttemptError as retry_exc:
                    return self._handle_streaming_attempt_error(
                        retry_exc,
                        messages=messages,
                        allow_refresh=True,
                        event_cb=event_cb,
                    )
            return self._handle_streaming_attempt_error(
                exc,
                messages=messages,
                allow_refresh=True,
                event_cb=event_cb,
            )

    def _handle_streaming_attempt_error(
        self,
        exc: _StreamingAttemptError,
        *,
        messages: list[Any],
        allow_refresh: bool,
        event_cb: Any | None = None,
    ) -> Any:
        if not exc.stream_started and _looks_like_streaming_unsupported(exc.original):
            return self._invoke_once(messages, allow_refresh=allow_refresh, event_cb=event_cb)
        _raise_openai_error(exc.original, model=self._model, event_cb=event_cb)

    def _invoke_streaming_attempt(
        self,
        messages: list[Any],
        *,
        allow_refresh: bool,
        event_cb: Any | None = None,
        include_usage: bool,
    ) -> Any:
        http_client: httpx.Client | None = None
        diagnostics = _new_stream_diagnostics()
        try:
            api_key = self._resolve_api_key(allow_refresh=allow_refresh)
            if self._verify is not None:
                http_client = httpx.Client(verify=self._verify)
            client = OpenAI(
                api_key=api_key,
                base_url=self._base_url,
                default_headers=self._extra_headers or None,
                timeout=self._timeout,
                http_client=http_client,
            )
            request_kwargs = self._build_request_kwargs(messages)
            request_kwargs["stream"] = True
            if include_usage:
                request_kwargs["stream_options"] = {"include_usage": True}
            request_diagnostics = self._build_request_diagnostics(request_kwargs)
            stream = client.chat.completions.create(**request_kwargs)
            native_response, diagnostics = _stream_to_native_response(
                stream,
                model=self._model,
                event_cb=event_cb,
                diagnostics=diagnostics,
            )
            return _native_response_to_ai_message(
                self._AIMessage,
                native_response,
                request_summary=request_diagnostics,
                stream_diagnostics=diagnostics,
            )
        except _StreamingAttemptError:
            raise
        except Exception as exc:
            raise _StreamingAttemptError(
                exc,
                stream_started=bool(diagnostics.get("event_count")),
                include_usage=include_usage,
            ) from exc
        finally:
            if http_client is not None:
                http_client.close()

    def _invoke_once(
        self,
        messages: list[Any],
        *,
        allow_refresh: bool,
        event_cb: Any | None = None,
    ) -> Any:
        started_at = time.time()
        http_client: httpx.Client | None = None
        try:
            api_key = self._resolve_api_key(allow_refresh=allow_refresh)
            if self._verify is not None:
                http_client = httpx.Client(verify=self._verify)
            client = OpenAI(
                api_key=api_key,
                base_url=self._base_url,
                default_headers=self._extra_headers or None,
                timeout=self._timeout,
                http_client=http_client,
            )
            request_kwargs = self._build_request_kwargs(messages)
            request_diagnostics = self._build_request_diagnostics(request_kwargs)
            response = client.chat.completions.create(**request_kwargs)
            native_response = _response_to_native(response)
            completed_at = time.time()
            diagnostics = {
                "provider": _PROVIDER,
                "event_count": 1,
                "text_delta_count": 0,
                "text_chars": 0,
                "first_event_at": started_at,
                "first_text_delta_at": 0.0,
                "last_text_delta_at": 0.0,
                "completed_at": completed_at,
            }
            if event_cb is not None:
                event_cb(
                    {
                        "type": "response.completed",
                        "timestamp": completed_at,
                        "model": self._model,
                        "provider": _PROVIDER,
                        "diagnostics": dict(diagnostics),
                    }
                )
            return _native_response_to_ai_message(
                self._AIMessage,
                native_response,
                request_summary=request_diagnostics,
                stream_diagnostics=diagnostics,
            )
        except Exception as exc:
            _raise_openai_error(exc, model=self._model, event_cb=event_cb)
        finally:
            if http_client is not None:
                http_client.close()

    def _build_request_kwargs(self, messages: list[Any]) -> dict[str, Any]:
        request_kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": encode_messages(messages),
            "max_tokens": self._max_output_tokens,
        }
        if self._temperature is not None:
            request_kwargs["temperature"] = float(self._temperature)
        tool_payloads = build_openai_tools(self._tools)
        if tool_payloads:
            request_kwargs["tools"] = tool_payloads
            request_kwargs["tool_choice"] = "auto"
        return request_kwargs

    def _build_request_diagnostics(self, request_kwargs: dict[str, Any]) -> dict[str, Any]:
        return build_request_summary(
            backend=_PROVIDER,
            provider=self._provider,
            model=self._model,
            streaming=bool(request_kwargs.get("stream")),
            api_path="chat_completions",
            messages=list(request_kwargs.get("messages") or []),
            max_output_tokens=int(request_kwargs.get("max_tokens") or 0) or self._max_output_tokens,
            temperature=request_kwargs.get("temperature"),
            tools_available_count=len(self._tools),
            tools_exposed=bool(request_kwargs.get("tools")),
            tool_choice=str(request_kwargs.get("tool_choice") or "none"),
            tool_count_exposed=len(list(request_kwargs.get("tools") or [])),
        )

    def _resolve_api_key(self, *, allow_refresh: bool) -> str:
        if self._auth_manager is not None:
            auth = self._auth_manager.require(allow_refresh=allow_refresh)
            if auth.mode != "api_key":
                raise RuntimeError(f"OpenAI native adapter requires api_key auth, got {auth.mode}.")
            api_key = str(auth.api_key or "").strip()
        else:
            api_key = str(self._api_key or "").strip()
        if not api_key:
            raise RuntimeError("OpenAI API key is not configured.")
        return api_key


def _response_to_native(response: Any) -> NativeLLMResponse:
    choices = list(getattr(response, "choices", None) or [])
    if not choices:
        raise RuntimeError("OpenAI response returned no choices.")

    choice = choices[0]
    message = getattr(choice, "message", None)
    if message is None:
        raise RuntimeError("OpenAI response choice did not include a message.")

    return NativeLLMResponse(
        content=_message_content_to_text(getattr(message, "content", "")),
        tool_calls=_tool_calls_to_native(getattr(message, "tool_calls", None) or []),
        raw=response,
        finish_reason=str(getattr(choice, "finish_reason", "") or ""),
        usage=_usage_to_payload(getattr(response, "usage", None)),
        response_id=str(getattr(response, "id", "") or ""),
        model=str(getattr(response, "model", "") or ""),
    )


def _stream_to_native_response(
    stream: Any,
    *,
    model: str,
    event_cb: Any | None,
    diagnostics: dict[str, Any],
) -> tuple[NativeLLMResponse, dict[str, Any]]:
    text_parts: list[str] = []
    tool_call_buffers: dict[int, dict[str, str]] = {}
    response_id = ""
    response_model = ""
    finish_reason = ""
    usage_payload = _usage_to_payload(None)

    for chunk in stream:
        now = time.time()
        diagnostics["event_count"] = int(diagnostics.get("event_count") or 0) + 1
        if not diagnostics.get("first_event_at"):
            diagnostics["first_event_at"] = now
        response_id = str(getattr(chunk, "id", "") or response_id)
        response_model = str(getattr(chunk, "model", "") or response_model)
        usage_payload = _merge_usage_payload(usage_payload, _usage_to_payload(getattr(chunk, "usage", None)))

        choices = list(getattr(chunk, "choices", None) or [])
        if not choices:
            continue

        choice = choices[0]
        finish_reason = str(getattr(choice, "finish_reason", "") or finish_reason)
        delta = getattr(choice, "delta", None)
        if delta is None:
            continue

        text_delta = _message_content_to_text(getattr(delta, "content", ""))
        if text_delta:
            text_parts.append(text_delta)
            diagnostics["text_delta_count"] = int(diagnostics.get("text_delta_count") or 0) + 1
            diagnostics["text_chars"] = int(diagnostics.get("text_chars") or 0) + len(text_delta)
            if not diagnostics.get("first_text_delta_at"):
                diagnostics["first_text_delta_at"] = now
            diagnostics["last_text_delta_at"] = now
            if event_cb is not None:
                event_cb(
                    {
                        "type": "response.output_text.delta",
                        "delta": text_delta,
                        "timestamp": now,
                        "model": model,
                        "provider": _PROVIDER,
                    }
                )

        for call_delta in list(getattr(delta, "tool_calls", None) or []):
            _merge_tool_call_delta(tool_call_buffers, call_delta)

    if not diagnostics.get("event_count"):
        raise RuntimeError("OpenAI response stream completed without emitting any chunks.")

    completed_at = time.time()
    diagnostics["completed_at"] = completed_at
    if event_cb is not None:
        event_cb(
            {
                "type": "response.completed",
                "timestamp": completed_at,
                "model": model,
                "provider": _PROVIDER,
                "diagnostics": dict(diagnostics),
            }
        )

    return (
        NativeLLMResponse(
            content="".join(text_parts),
            tool_calls=_tool_call_buffers_to_native(tool_call_buffers),
            raw=None,
            finish_reason=finish_reason,
            usage=usage_payload,
            response_id=response_id,
            model=response_model or model,
        ),
        diagnostics,
    )


def _tool_calls_to_native(tool_calls: list[Any]) -> list[NativeLLMToolCall]:
    native_calls: list[NativeLLMToolCall] = []
    for index, call in enumerate(tool_calls, start=1):
        function = getattr(call, "function", None)
        raw_arguments = str(getattr(function, "arguments", "") or "")
        native_calls.append(
            NativeLLMToolCall(
                id=str(getattr(call, "id", "") or f"call_{index}"),
                name=str(getattr(function, "name", "") or ""),
                arguments=_parse_tool_arguments(raw_arguments),
                raw_arguments=raw_arguments,
            )
        )
    return native_calls


def _tool_call_buffers_to_native(buffers: dict[int, dict[str, str]]) -> list[NativeLLMToolCall]:
    tool_calls: list[NativeLLMToolCall] = []
    for index in sorted(buffers):
        item = dict(buffers.get(index) or {})
        raw_arguments = str(item.get("arguments", "") or "")
        tool_calls.append(
            NativeLLMToolCall(
                id=str(item.get("id", "") or f"call_{index + 1}"),
                name=str(item.get("name", "") or ""),
                arguments=_parse_tool_arguments(raw_arguments),
                raw_arguments=raw_arguments,
            )
        )
    return tool_calls


def _merge_tool_call_delta(buffers: dict[int, dict[str, str]], call_delta: Any) -> None:
    try:
        index = int(getattr(call_delta, "index", len(buffers)) or 0)
    except Exception:
        index = len(buffers)
    item = buffers.setdefault(index, {"id": "", "name": "", "arguments": ""})

    call_id = str(getattr(call_delta, "id", "") or "")
    if call_id:
        item["id"] = call_id

    function = getattr(call_delta, "function", None)
    name_piece = str(getattr(function, "name", "") or "")
    if name_piece:
        item["name"] = _merge_stream_piece(item["name"], name_piece)

    arguments_piece = str(getattr(function, "arguments", "") or "")
    if arguments_piece:
        item["arguments"] = f"{item['arguments']}{arguments_piece}"


def _native_response_to_ai_message(
    ai_message_cls: Any,
    response: NativeLLMResponse,
    *,
    request_summary: dict[str, Any] | None = None,
    stream_diagnostics: dict[str, Any] | None = None,
) -> Any:
    tool_calls = [
        {
            "name": call.name,
            "args": dict(call.arguments),
            "raw_args": call.raw_arguments,
            "id": call.id,
            "type": "tool_call",
        }
        for call in response.tool_calls
    ]
    message = ai_message_cls(
        content=response.content,
        tool_calls=tool_calls,
        usage_metadata=dict(response.usage),
        response_metadata={
            "token_usage": dict(response.usage),
            "provider": _PROVIDER,
            "response_id": response.response_id,
            "model": response.model,
            "finish_reason": response.finish_reason,
            "request_summary": dict(request_summary or {}),
            "stream_diagnostics": dict(stream_diagnostics or _new_stream_diagnostics()),
        },
    )
    response_metadata = getattr(message, "response_metadata", None)
    if isinstance(response_metadata, dict):
        response_metadata["assistant_response_summary"] = build_assistant_response_summary_from_message(message)
    return message


def _new_stream_diagnostics() -> dict[str, Any]:
    return {
        "provider": _PROVIDER,
        "event_count": 0,
        "text_delta_count": 0,
        "text_chars": 0,
        "first_event_at": 0.0,
        "first_text_delta_at": 0.0,
        "last_text_delta_at": 0.0,
        "completed_at": 0.0,
    }


def _usage_to_payload(usage: Any) -> dict[str, int]:
    payload = {
        "input_tokens": int(getattr(usage, "prompt_tokens", getattr(usage, "input_tokens", 0)) or 0),
        "output_tokens": int(getattr(usage, "completion_tokens", getattr(usage, "output_tokens", 0)) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }
    if payload["total_tokens"] <= 0:
        payload["total_tokens"] = payload["input_tokens"] + payload["output_tokens"]
    return payload


def _merge_usage_payload(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    if not any(int(right.get(key, 0) or 0) for key in ("input_tokens", "output_tokens", "total_tokens")):
        return dict(left)
    merged = {
        "input_tokens": int(right.get("input_tokens", 0) or 0),
        "output_tokens": int(right.get("output_tokens", 0) or 0),
        "total_tokens": int(right.get("total_tokens", 0) or 0),
    }
    if merged["total_tokens"] <= 0:
        merged["total_tokens"] = merged["input_tokens"] + merged["output_tokens"]
    return merged


def _parse_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_arguments) if str(raw_arguments or "").strip() else {}
    except json.JSONDecodeError:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text_value = _content_part_to_text(item)
            if text_value:
                parts.append(text_value)
        return "".join(parts)
    if isinstance(content, dict):
        return _content_part_to_text(content)
    return str(content or "").strip()


def _content_part_to_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        text_value = item.get("text")
        if text_value is not None:
            return str(text_value)
        inner = item.get("content")
        if isinstance(inner, str):
            return inner
        return ""
    text_value = getattr(item, "text", None)
    if text_value is not None:
        return str(text_value)
    inner = getattr(item, "content", None)
    if isinstance(inner, str):
        return inner
    return ""


def _merge_stream_piece(existing: str, piece: str) -> str:
    if not piece:
        return str(existing or "")
    if not existing:
        return piece
    if existing == piece or existing.endswith(piece):
        return existing
    if piece.startswith(existing) or existing in piece:
        return piece
    max_overlap = min(len(existing), len(piece))
    for overlap in range(max_overlap, 0, -1):
        if existing.endswith(piece[:overlap]):
            return f"{existing}{piece[overlap:]}"
    return f"{existing}{piece}"


def _looks_like_stream_usage_error(exc: Exception) -> bool:
    text = _safe_error_text(exc).lower()
    return "stream_options" in text or ("include_usage" in text and "stream" in text)


def _looks_like_streaming_unsupported(exc: Exception) -> bool:
    text = _safe_error_text(exc).lower()
    if "stream" not in text:
        return False
    unsupported_hints = (
        "unsupported",
        "not supported",
        "does not support",
        "invalid parameter",
        "unknown parameter",
        "unrecognized request argument",
        "extra inputs are not permitted",
        "extra fields not permitted",
    )
    return any(hint in text for hint in unsupported_hints)


def _raise_openai_error(exc: Exception, *, model: str, event_cb: Any | None = None) -> Any:
    if isinstance(exc, AuthenticationError):
        error_text = f"OpenAI authentication failed: {_safe_error_text(exc)}"
    elif isinstance(exc, RateLimitError):
        error_text = f"OpenAI rate limit exceeded: {_safe_error_text(exc)}"
    elif isinstance(exc, APITimeoutError):
        error_text = f"OpenAI request timed out: {_safe_error_text(exc)}"
    elif isinstance(exc, APIConnectionError):
        error_text = f"OpenAI connection failed: {_safe_error_text(exc)}"
    elif isinstance(exc, BadRequestError):
        error_text = f"OpenAI bad request: {_safe_error_text(exc)}"
    elif isinstance(exc, APIError):
        error_text = f"OpenAI request failed: {_safe_error_text(exc)}"
    elif isinstance(exc, RuntimeError):
        error_text = str(exc)
    else:
        error_text = f"OpenAI request failed: {_safe_error_text(exc)}"
    _emit_failure_event(event_cb, model, error_text)
    raise RuntimeError(error_text) from exc


def _emit_failure_event(event_cb: Any | None, model: str, error_text: str) -> None:
    if event_cb is None:
        return
    event_cb(
        {
            "type": "response.failed",
            "timestamp": time.time(),
            "model": model,
            "provider": _PROVIDER,
            "error": error_text,
        }
    )


def _safe_error_text(exc: Exception) -> str:
    text = str(exc or "").strip()
    return text or exc.__class__.__name__
