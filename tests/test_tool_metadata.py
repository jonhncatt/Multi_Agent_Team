from __future__ import annotations

from app.config import load_config
from app.tool_metadata import TOOL_METADATA, get_tool_metadata, metadata_missing_names
from app.vintage_programmer_runtime import _READ_ONLY_TOOL_NAMES
from app.vp_support.tools import get_tool_executor


_ALLOWED_GROUPS = {
    "control",
    "shell",
    "edit",
    "file",
    "document",
    "web",
    "browser",
    "media",
    "session",
    "archive",
    "unknown",
}
_ALLOWED_SOURCES = {"native", "adapter", "optional", "legacy", "unknown"}
_ALLOWED_RISKS = {"low", "medium", "high", "unknown"}
_REQUIRE_KEYS = {"workspace_read", "workspace_write", "shell", "network", "browser", "optional_dependency"}


def _registered_tool_names() -> list[str]:
    config = load_config()
    executor = get_tool_executor(config)
    return [str(item.get("name") or "") for item in executor.tool_specs if str(item.get("name") or "")]


def test_all_registered_tools_have_metadata() -> None:
    assert metadata_missing_names(_registered_tool_names()) == []


def test_no_legacy_source_labels_in_metadata() -> None:
    banned = {"codex_core", "openclaw_inspired", "openclaw_fallback"}
    for name, meta in TOOL_METADATA.items():
        assert str(meta.get("group") or "") in _ALLOWED_GROUPS, name
        assert str(meta.get("source") or "") in _ALLOWED_SOURCES, name
        assert str(meta.get("group") or "") not in banned, name
        assert str(meta.get("source") or "") not in banned, name


def test_metadata_requires_shape_is_valid() -> None:
    for name, meta in TOOL_METADATA.items():
        requires = dict(meta.get("requires") or {})
        assert set(requires) == _REQUIRE_KEYS, name
        for key in ("workspace_read", "workspace_write", "shell", "network", "browser"):
            assert isinstance(requires[key], bool), f"{name}:{key}"
        assert isinstance(requires["optional_dependency"], list), name
        assert str(meta.get("risk") or "") in _ALLOWED_RISKS, name


def test_unknown_tool_metadata_uses_safe_fallback() -> None:
    meta = get_tool_metadata("missing_tool")

    assert meta["group"] == "unknown"
    assert meta["source"] == "unknown"
    assert meta["requires"]["workspace_read"] is False
    assert meta["requires"]["workspace_write"] is False
    assert meta["requires"]["shell"] is False
    assert meta["requires"]["network"] is False
    assert meta["requires"]["browser"] is False


def test_read_only_tool_policy_only_exposes_metadata_read_only_tools() -> None:
    for name in sorted(_READ_ONLY_TOOL_NAMES):
        meta = get_tool_metadata(name)
        assert meta["read_only"] is True, name
