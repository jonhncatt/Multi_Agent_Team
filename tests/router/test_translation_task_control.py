from __future__ import annotations

from tests.router.support import pdf_attachment, run_pipeline, translation_active_task


def test_initial_pdf_translation_creates_active_task_via_llm_first_path() -> None:
    result = run_pipeline(
        message="请把这个 PDF 从第1句开始翻译成中文",
        attachments=[pdf_attachment(attachment_id="pdf-doc")],
        llm_available=True,
        llm_payload={
            "task_kind": "document_translation",
            "intent": "understanding",
            "sub_intent": "translation",
            "target": "pdf-doc",
            "needs_tools": True,
            "needs_file_context": True,
            "needs_web": False,
            "task_control": {
                "start": True,
                "resume": False,
                "mode_switch": None,
                "position_reset": "sentence:1",
            },
            "confidence": 0.94,
            "reason_short": "translate the uploaded pdf from sentence 1",
        },
    )
    decision = result["decision"]
    route = result["route"]
    trace = result["trace"]
    signals = result["signals"]

    assert decision.source == "llm"
    assert decision.task_kind == "document_translation"
    assert decision.task_control.start is True
    assert decision.task_control.position_reset == "sentence:1"
    assert signals.translation_request is True
    assert signals.translation_position_reset_like is True
    assert signals.translation_followup_like is True
    assert route["execution_policy"] == "translation_session_pipeline"
    assert route["active_task"]["task_kind"] == "document_translation"
    assert route["active_task"]["target_id"] == "pdf-doc"
    assert route["active_task"]["started"] is True
    assert route["active_task"]["progress"]["position"] == "sentence:1"
    assert route["active_task_kind"] == "document_translation"
    assert route["task_control_position"] == "sentence:1"
    assert "task_kind=document_translation" in trace.active_task_summary
    assert trace.chosen_execution_policy == "translation_session_pipeline"
    assert trace.active_task_kind == "document_translation"
    assert trace.task_control_position == "sentence:1"


def test_active_translation_task_switches_to_sentence_mode_without_reprompt() -> None:
    result = run_pipeline(
        message="逐句翻译",
        route_state={"active_task": translation_active_task(target_id="pdf-doc", progress={"position": "sentence:4"})},
    )
    decision = result["decision"]
    frame = result["frame"]
    route = result["route"]
    signals = result["signals"]
    trace = result["trace"]

    assert decision.top_intent == "continue_existing_task"
    assert decision.task_control.mode_switch == "sentence_by_sentence"
    assert decision.requires_clarifying_route is False
    assert signals.translation_followup_like is True
    assert signals.translation_mode_switch_like is True
    assert frame.current_task_type == "document_translation"
    assert frame.current_document_id == "pdf-doc"
    assert frame.current_operation_mode == "full"
    assert frame.current_position == "sentence:4"
    assert route["execution_policy"] == "translation_session_pipeline"
    assert route["active_task"]["mode"] == "sentence_by_sentence"
    assert route["active_task_kind"] == "document_translation"
    assert route["task_control_mode"] == "sentence_by_sentence"
    assert trace.active_task_kind == "document_translation"
    assert trace.task_control_mode == "sentence_by_sentence"
    assert route["verifier_actions"] == []


def test_active_translation_task_start_executes_directly() -> None:
    result = run_pipeline(
        message="开始",
        route_state={"active_task": translation_active_task(target_id="pdf-doc")},
    )
    decision = result["decision"]
    signals = result["signals"]
    route = result["route"]

    assert decision.task_control.start is True
    assert signals.translation_start_like is True
    assert signals.translation_followup_like is True
    assert route["execution_policy"] == "translation_session_pipeline"
    assert route["active_task"]["started"] is True
    assert route["active_task"]["last_user_control"] == "start"
    assert route["active_task_kind"] == "document_translation"


def test_active_translation_task_can_reset_progress_and_execute() -> None:
    result = run_pipeline(
        message="从第1句开始翻译",
        route_state={"active_task": translation_active_task(target_id="pdf-doc", progress={"position": "sentence:9"})},
    )
    decision = result["decision"]
    frame = result["frame"]
    signals = result["signals"]
    route = result["route"]
    trace = result["trace"]

    assert decision.task_control.position_reset == "sentence:1"
    assert signals.translation_position_reset_like is True
    assert signals.translation_followup_like is True
    assert frame.current_task_type == "document_translation"
    assert frame.current_position == "sentence:9"
    assert route["execution_policy"] == "translation_session_pipeline"
    assert route["active_task"]["progress"]["position"] == "sentence:1"
    assert route["active_task"]["last_user_control"] == "position_reset:sentence:1"
    assert route["task_control_position"] == "sentence:1"
    assert trace.task_control_position == "sentence:1"


def test_sentence_by_sentence_without_active_task_goes_to_safe_clarifying_route() -> None:
    result = run_pipeline(message="逐句翻译")
    decision = result["decision"]
    route = result["route"]
    signals = result["signals"]
    trace = result["trace"]

    assert decision.requires_clarifying_route is True
    assert signals.translation_mode_switch_like is True
    assert signals.translation_followup_like is True
    assert route["execution_policy"] == "standard_safe_pipeline"
    assert trace.chosen_execution_policy == "standard_safe_pipeline"


def test_llm_unavailable_falls_back_without_task_control_loop() -> None:
    result = run_pipeline(
        message="逐句翻译",
        llm_available=False,
    )
    decision = result["decision"]
    route = result["route"]
    signals = result["signals"]
    trace = result["trace"]

    assert decision.source == "rules"
    assert decision.escalation_reason == "llm_unavailable"
    assert decision.requires_clarifying_route is True
    assert signals.translation_mode_switch_like is True
    assert route["execution_policy"] == "standard_safe_pipeline"
    assert trace.llm_escalated is False
