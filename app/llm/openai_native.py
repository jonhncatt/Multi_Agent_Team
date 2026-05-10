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

from app.openai_auth import OpenAIAuthManager

from .message_codec import encode_messages
from .tool_schema import build_openai_tools
from .types import AIMessage, NativeLLMResponse, NativeLLMToolCall


class OpenAINativeLLMAdapter:
    def __init__(
        self,
        *,
        auth_manager: OpenAIAuthManager | None = None,
        api_key: str | None = None,
        base_url: str | None,
        model: str,
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
        return self._invoke_once(messages, allow_refresh=True, event_cb=event_cb)

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
            response = client.chat.completions.create(**request_kwargs)
            native_response = _response_to_native(response)
            completed_at = time.time()
            if event_cb is not None:
                event_cb(
                    {
                        "type": "response.completed",
                        "timestamp": completed_at,
                        "model": self._model,
                        "provider": "openai_native",
                        "diagnostics": {
                            "provider": "openai_native",
                            "event_count": 1,
                            "text_delta_count": 0,
                            "text_chars": 0,
                            "first_event_at": started_at,
                            "first_text_delta_at": 0.0,
                            "last_text_delta_at": 0.0,
                            "completed_at": completed_at,
                        },
                    }
                )
            return _native_response_to_ai_message(self._AIMessage, native_response)
        except AuthenticationError as exc:
            _emit_failure_event(event_cb, self._model, f"OpenAI authentication failed: {_safe_error_text(exc)}")
            raise RuntimeError(f"OpenAI authentication failed: {_safe_error_text(exc)}") from exc
        except RateLimitError as exc:
            _emit_failure_event(event_cb, self._model, f"OpenAI rate limit exceeded: {_safe_error_text(exc)}")
            raise RuntimeError(f"OpenAI rate limit exceeded: {_safe_error_text(exc)}") from exc
        except APITimeoutError as exc:
            _emit_failure_event(event_cb, self._model, f"OpenAI request timed out: {_safe_error_text(exc)}")
            raise RuntimeError(f"OpenAI request timed out: {_safe_error_text(exc)}") from exc
        except APIConnectionError as exc:
            _emit_failure_event(event_cb, self._model, f"OpenAI connection failed: {_safe_error_text(exc)}")
            raise RuntimeError(f"OpenAI connection failed: {_safe_error_text(exc)}") from exc
        except BadRequestError as exc:
            _emit_failure_event(event_cb, self._model, f"OpenAI bad request: {_safe_error_text(exc)}")
            raise RuntimeError(f"OpenAI bad request: {_safe_error_text(exc)}") from exc
        except APIError as exc:
            _emit_failure_event(event_cb, self._model, f"OpenAI request failed: {_safe_error_text(exc)}")
            raise RuntimeError(f"OpenAI request failed: {_safe_error_text(exc)}") from exc
        finally:
            if http_client is not None:
                http_client.close()

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

    tool_calls: list[NativeLLMToolCall] = []
    for index, call in enumerate(getattr(message, "tool_calls", None) or [], start=1):
        function = getattr(call, "function", None)
        raw_arguments = str(getattr(function, "arguments", "") or "")
        try:
            parsed_arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
        except json.JSONDecodeError:
            parsed_arguments = {}
        tool_calls.append(
            NativeLLMToolCall(
                id=str(getattr(call, "id", "") or f"call_{index}"),
                name=str(getattr(function, "name", "") or ""),
                arguments=parsed_arguments if isinstance(parsed_arguments, dict) else {},
                raw_arguments=raw_arguments,
            )
        )

    usage = getattr(response, "usage", None)
    usage_payload = {
        "input_tokens": int(getattr(usage, "prompt_tokens", getattr(usage, "input_tokens", 0)) or 0),
        "output_tokens": int(getattr(usage, "completion_tokens", getattr(usage, "output_tokens", 0)) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }
    if usage_payload["total_tokens"] <= 0:
        usage_payload["total_tokens"] = usage_payload["input_tokens"] + usage_payload["output_tokens"]

    return NativeLLMResponse(
        content=_message_content_to_text(getattr(message, "content", "")),
        tool_calls=tool_calls,
        raw=response,
        finish_reason=str(getattr(choice, "finish_reason", "") or ""),
        usage=usage_payload,
        response_id=str(getattr(response, "id", "") or ""),
        model=str(getattr(response, "model", "") or ""),
    )


def _native_response_to_ai_message(ai_message_cls: Any, response: NativeLLMResponse) -> Any:
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
    return ai_message_cls(
        content=response.content,
        tool_calls=tool_calls,
        usage_metadata=dict(response.usage),
        response_metadata={
            "token_usage": dict(response.usage),
            "provider": "openai_native",
            "response_id": response.response_id,
            "model": response.model,
            "finish_reason": response.finish_reason,
            "stream_diagnostics": {
                "provider": "openai_native",
                "event_count": 1,
                "text_delta_count": 0,
                "text_chars": 0,
                "first_event_at": 0.0,
                "first_text_delta_at": 0.0,
                "last_text_delta_at": 0.0,
                "completed_at": 0.0,
            },
        },
    )


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text_value = getattr(item, "text", None)
            if text_value:
                parts.append(str(text_value))
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _emit_failure_event(event_cb: Any | None, model: str, error_text: str) -> None:
    if event_cb is None:
        return
    event_cb(
        {
            "type": "response.failed",
            "timestamp": time.time(),
            "model": model,
            "provider": "openai_native",
            "error": error_text,
        }
    )


def _safe_error_text(exc: Exception) -> str:
    text = str(exc or "").strip()
    return text or exc.__class__.__name__
