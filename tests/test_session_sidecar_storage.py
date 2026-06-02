from __future__ import annotations

import json
from pathlib import Path

from app.storage import SessionStore


def _project(tmp_path: Path) -> dict[str, str]:
    return {
        "project_id": "project-test",
        "title": "Test Project",
        "root_path": str(tmp_path),
        "git_branch": "main",
    }


def test_assistant_activity_is_slimmed_to_run_sidecar(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(_project(tmp_path))
    store.append_turn(session, role="user", text="inspect")
    assistant_turn = store.append_turn(
        session,
        role="assistant",
        text="done",
        answer_bundle={"summary": "done", "claims": [], "citations": [], "warnings": []},
        activity={
            "run_id": "run-1",
            "status": "completed",
            "activity_summary": "read and answered",
            "run_duration_ms": 12,
            "trace_events": [{"id": "trace-1", "type": "tool.started", "payload": {"call_id": "call-1"}}],
            "llm_exchanges": [{"round": 1, "status": "completed"}],
            "model_draft": "draft",
            "final_answer": "done",
        },
    )

    store.persist_turn_artifact(
        session,
        turn_id=assistant_turn["id"],
        run_id="run-1",
        activity=assistant_turn["activity"],
        answer_bundle=assistant_turn["answer_bundle"],
        tool_events=[{"name": "read_file", "status": "ok", "summary": "read"}],
        inspector={"run_state": {"turn_status": "completed"}},
    )
    store.save(session)

    raw_session = json.loads((tmp_path / "sessions" / f"{session['id']}.json").read_text(encoding="utf-8"))
    raw_activity = raw_session["turns"][-1]["activity"]
    assert raw_activity["trace_ref"] == f"{session['id']}/run-1"
    assert raw_activity["tool_count"] == 1
    assert "trace_events" not in raw_activity
    assert "llm_exchanges" not in raw_activity
    assert raw_session["turns"][-1]["answer_bundle"] == {}

    sidecar = json.loads((tmp_path / "runs" / session["id"] / "run-1.json").read_text(encoding="utf-8"))
    assert sidecar["activity"]["trace_events"][0]["id"] == "trace-1"
    assert sidecar["answer_bundle"]["summary"] == "done"
    assert sidecar["tool_events"][0]["name"] == "read_file"

    summary_turn = store.expand_turn_for_view(session["id"], raw_session["turns"][-1], view="summary")
    assert summary_turn["answer_bundle"] == {}
    assert "trace_events" not in summary_turn["activity"]

    full_turn = store.expand_turn_for_view(session["id"], raw_session["turns"][-1], view="full")
    assert full_turn["answer_bundle"]["summary"] == "done"
    assert full_turn["activity"]["trace_events"][0]["id"] == "trace-1"
    assert full_turn["run_artifact"]["inspector"]["run_state"]["turn_status"] == "completed"


def test_session_list_reads_metadata_without_parsing_session_file(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(_project(tmp_path))
    store.append_turn(session, role="user", text="hello")
    store.save(session)

    session_path = tmp_path / "sessions" / f"{session['id']}.json"
    session_path.write_text("{not-json", encoding="utf-8")

    rows = store.list_recent_sessions(limit=10, project_id="project-test")
    assert [row["session_id"] for row in rows] == [session["id"]]
    assert rows[0]["title"] == "hello"
