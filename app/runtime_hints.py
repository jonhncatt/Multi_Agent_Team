from __future__ import annotations

import re
from typing import Any

from app.tool_trace_summary import safe_preview


_EXPLICIT_NETWORK_HINTS = (
    "最新",
    "news",
    "today",
    "网页",
    "web",
    "search",
    "搜索",
    "检索",
    "截图",
    "screenshot",
    "浏览器",
    "playwright",
    "image",
    "http://",
    "https://",
    "www.",
)

_EXPLICIT_WORKSPACE_HINTS = (
    "当前工作区",
    "整个仓库",
    "整个代码库",
    "这个仓库",
    "这个 repo",
    "repo",
    "codebase",
    "目录",
    "文件树",
    "读取文件",
    "打开文件",
    "查看文件",
    "修改文件",
    "补丁",
    "patch",
    "skill",
    "skills",
    "soul.md",
    "identity.md",
    "agent.md",
    "tools.md",
    "终端",
    "shell",
    "命令行",
    "命令",
    "run shell",
    "执行命令",
)

_INLINE_DOC_CODE_FENCE_HINTS = (
    "```xml",
    "```html",
    "```json",
    "```yaml",
    "```yml",
    "```rss",
    "```atom",
    "```python",
    "```py",
    "```ts",
    "```tsx",
    "```js",
    "```jsx",
)

_REVISION_REQUEST_HINTS = (
    "润色",
    "改写",
    "改成",
    "重写",
    "校对",
    "语法",
    "文法",
    "proofread",
    "grammar",
    "rewrite",
    "rephrase",
    "polish",
    "revise",
    "edit",
    "more natural",
)

_JAPANESE_REQUEST_HINTS = (
    "日语",
    "日文",
    "日本语",
    "日本語",
    "japanese",
    "敬语",
    "敬語",
)

_JAPANESE_KANA_RE = re.compile(r"[ぁ-んァ-ヶ]")

_MISSING_CONTEXT_RESPONSE_HINTS = (
    "没有提供任何任务",
    "没有提供任何上下文",
    "没有提供任何需要我处理的具体任务",
    "请告诉我你需要我做什么",
    "请您告诉我",
    "you have not provided any task",
    "you haven't provided any task",
    "you have not provided any context",
    "you haven't provided any context",
    "please tell me what you need me to do",
)

_GENERIC_IMAGE_READ_REQUEST_HINTS = (
    "看看图片内容",
    "解释图片内容",
    "看图",
    "读图",
    "读取图片",
    "读取截图",
    "识别图片",
    "识别截图",
    "提取图片文字",
    "提取截图文字",
    "图片里写了什么",
)


def contains_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(str(item).lower() in lowered for item in hints)


def has_explicit_network_hint(text: str) -> bool:
    return contains_any(text, _EXPLICIT_NETWORK_HINTS)


def has_explicit_workspace_hint(text: str) -> bool:
    return contains_any(text, _EXPLICIT_WORKSPACE_HINTS)


def looks_like_inline_code_payload(text: str) -> bool:
    raw = str(text or "").strip()
    if len(raw) < 60:
        return False
    fenced_blocks = re.findall(r"```[A-Za-z0-9_+.-]*\n([\s\S]{80,}?)```", raw)
    code_markers = (
        "def ",
        "class ",
        "return ",
        "import ",
        "from ",
        "const ",
        "let ",
        "function ",
        "public ",
        "private ",
        "if (",
        "=>",
        "</",
        "{",
        "};",
    )
    if any(any(marker in block for marker in code_markers) for block in fenced_blocks[:3]):
        return True
    lines = [line.rstrip() for line in raw.splitlines() if line.strip()]
    if len(lines) < 6:
        return False
    marker_hits = sum(1 for line in lines[:40] if any(marker in line for marker in code_markers))
    punctuation_hits = sum(1 for line in lines[:40] if line.count("{") + line.count("}") + line.count(";") >= 1)
    return marker_hits >= 4 or (marker_hits >= 2 and punctuation_hits >= 4)


def looks_like_inline_document_payload(text: str) -> bool:
    raw = str(text or "").strip()
    lowered = raw.lower()
    if any(marker in lowered for marker in _INLINE_DOC_CODE_FENCE_HINTS):
        return True
    if len(raw) < 60:
        return False
    if "<?xml" in lowered:
        return True
    if looks_like_inline_code_payload(raw):
        return True
    xml_tag_matches = re.findall(r"</?[a-zA-Z_][\w:.-]*(?:\s[^<>]{0,200})?>", raw)
    if len(xml_tag_matches) >= 6 and ("\n" in raw or len(raw) >= 240):
        return True
    json_key_count = len(re.findall(r'"[^"\n]{1,80}"\s*:', raw))
    if json_key_count >= 4 and len(raw) >= 180:
        return True
    yaml_key_count = len(re.findall(r"(?m)^[A-Za-z0-9_.-]{1,60}:\s+\S", raw))
    return yaml_key_count >= 5 and len(raw) >= 180


def looks_like_revision_request(text: str, *, route_state: dict[str, Any] | None = None) -> bool:
    route = dict(route_state or {})
    if bool(route.get("use_revision")):
        return True
    raw = str(text or "")
    lowered = raw.lower()
    return any(token in raw for token in _REVISION_REQUEST_HINTS) or any(token in lowered for token in _REVISION_REQUEST_HINTS)


def looks_like_japanese_request(text: str) -> bool:
    raw = str(text or "")
    lowered = raw.lower()
    return any(token in raw for token in _JAPANESE_REQUEST_HINTS) or any(token in lowered for token in _JAPANESE_REQUEST_HINTS) or bool(
        _JAPANESE_KANA_RE.search(raw)
    )


def looks_like_japanese_review_request(text: str, *, route_state: dict[str, Any] | None = None) -> bool:
    route = dict(route_state or {})
    route_task_type = str(route.get("task_type") or "").strip().lower()
    if route_task_type == "translation_session":
        return False
    return looks_like_revision_request(text, route_state=route) and looks_like_japanese_request(text)


def extract_activity_excerpt(text: str, *, prefer_japanese: bool = False) -> str:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = " ".join(str(raw_line or "").split())
        if not line:
            continue
        for separator in ("：", ":"):
            if separator in line:
                prefix, suffix = line.split(separator, 1)
                candidate = suffix.strip()
                if candidate and (bool(_JAPANESE_KANA_RE.search(candidate)) or len(candidate) >= len(prefix.strip())):
                    line = candidate
                    break
        lines.append(line)
    if prefer_japanese:
        japanese_lines = [line for line in lines if _JAPANESE_KANA_RE.search(line)]
        if japanese_lines:
            return str(safe_preview(" / ".join(japanese_lines[:2]), limit=220) or "")
    candidates = [line for line in lines if len(line) >= 8] or lines
    if not candidates:
        return ""
    return str(safe_preview(" / ".join(candidates[:2]), limit=220) or "")


def contains_missing_context_response_hint(text: str) -> bool:
    return contains_any(text, _MISSING_CONTEXT_RESPONSE_HINTS)


def is_generic_image_read_request(text: str) -> bool:
    return contains_any(text, _GENERIC_IMAGE_READ_REQUEST_HINTS)
