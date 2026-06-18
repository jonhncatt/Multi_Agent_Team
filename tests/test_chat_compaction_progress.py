from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_PY_PATH = REPO_ROOT / "app" / "main.py"
I18N_PATH = REPO_ROOT / "app" / "i18n.py"


def test_pre_turn_compaction_emits_started_before_running_compactor() -> None:
    source = MAIN_PY_PATH.read_text(encoding="utf-8")

    required_tokens = (
        "pre_compaction_probe = _build_compaction_status_for_session(",
        'pre_compaction_limit = int(pre_compaction_probe.get("auto_compact_token_limit") or 0)',
        "pre_compaction_estimated >= pre_compaction_limit",
        '\"type\": \"contextCompaction\"',
        '\"status\": \"inProgress\"',
        '\"summary\": translate(locale, \"chat.replacement_history_compacting\")',
        "compaction_result = maybe_auto_compact_session(",
        "if not pre_compaction_started_item:",
        "elif pre_compaction_started_item:",
        '\"summary\": translate(locale, \"chat.replacement_history_compaction_checked\")',
    )
    for token in required_tokens:
        assert token in source, token

    started_index = source.index('\"summary\": translate(locale, \"chat.replacement_history_compacting\")')
    compactor_index = source.index("compaction_result = maybe_auto_compact_session(")
    assert started_index < compactor_index


def test_pre_turn_compaction_progress_strings_are_localized() -> None:
    source = I18N_PATH.read_text(encoding="utf-8")

    for key in (
        "chat.replacement_history_compacting",
        "chat.replacement_history_compaction_checked",
    ):
        assert source.count(f'"{key}"') == 3
