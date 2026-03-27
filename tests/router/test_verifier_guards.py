from __future__ import annotations

from app.intent_schema import ConversationFrame, IntentDecision, RequestSignals
from app.route_verifier import RouteVerifier


def test_verifier_enables_planner_for_mixed_intent() -> None:
    verifier = RouteVerifier()
    route, _ = verifier.verify(
        decision=IntentDecision(top_intent="understanding", second_intent="generation", mixed_intent=True),
        route={"execution_policy": "mixed_intent_planner_pipeline", "use_planner": False},
        signals=RequestSignals(),
        frame=ConversationFrame(),
    )
    assert route["use_planner"] is True
    assert "force_enable_planner" in route["verifier_actions"]


def test_verifier_enables_worker_tools_when_required() -> None:
    verifier = RouteVerifier()
    route, _ = verifier.verify(
        decision=IntentDecision(top_intent="code_lookup", requires_tools=True),
        route={"execution_policy": "code_lookup_with_tools", "use_worker_tools": False},
        signals=RequestSignals(),
        frame=ConversationFrame(),
    )
    assert route["use_worker_tools"] is True
    assert "force_enable_worker_tools" in route["verifier_actions"]


def test_verifier_does_not_rewrite_plain_understanding_route() -> None:
    verifier = RouteVerifier()
    route, _ = verifier.verify(
        decision=IntentDecision(top_intent="understanding"),
        route={
            "task_type": "understanding",
            "execution_policy": "understanding_direct",
            "use_planner": False,
            "use_worker_tools": False,
        },
        signals=RequestSignals(),
        frame=ConversationFrame(dominant_intent="understanding"),
    )
    assert route["execution_policy"] == "understanding_direct"
    assert route["verifier_actions"] == []


def test_verifier_reroutes_translation_task_control_out_of_safe_pipeline() -> None:
    verifier = RouteVerifier()
    route, _ = verifier.verify(
        decision=IntentDecision(
            top_intent="continue_existing_task",
            task_kind="document_translation",
            task_control={"resume": True},
        ),
        route={
            "task_type": "standard",
            "execution_policy": "standard_safe_pipeline",
            "use_planner": True,
            "use_worker_tools": False,
            "active_task": {
                "task_id": "task_pdf_translation",
                "task_kind": "document_translation",
                "target_id": "pdf-doc",
                "target_type": "pdf",
                "mode": "full",
                "progress": {},
                "started": False,
                "finished": False,
                "last_user_control": "",
            },
        },
        signals=RequestSignals(translation_request=True, task_control_request=True),
        frame=ConversationFrame(dominant_intent="continue_existing_task"),
    )
    assert route["execution_policy"] == "translation_session_pipeline"
    assert route["active_task_kind"] == "document_translation"
    assert route["task_control_position"] == ""
    assert "reroute_to_translation_session_pipeline" in route["verifier_actions"]
