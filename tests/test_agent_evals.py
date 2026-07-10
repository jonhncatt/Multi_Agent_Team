from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app.agent_evals import (
    DEFAULT_CASES_PATH,
    EvalConfigurationError,
    aggregate_eval_results,
    analyze_tool_evidence,
    compare_snapshots,
    eval_exit_code,
    execute_authoritative_verifier,
    load_eval_suite,
    run_eval_attempt,
    scan_c_style_rules,
    snapshot_workspace,
)
from app.config import load_config


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evals" / "fixtures" / "agent_quality" / "c_style_cpp_protocol_frame_parser"


def _case() -> dict:
    suite = load_eval_suite(DEFAULT_CASES_PATH)
    return dict(suite["cases"][0])


def _write_exit_script(path: Path, returncode: int, *, sleep_sec: float = 0.0) -> None:
    body = "from __future__ import annotations\nimport sys\n"
    if sleep_sec:
        body += f"import time\ntime.sleep({sleep_sec!r})\n"
    body += f"print('wrapper-result-{returncode}')\nsys.exit({returncode})\n"
    path.write_text(body, encoding="utf-8")


def test_default_agent_quality_suite_is_valid() -> None:
    suite = load_eval_suite(DEFAULT_CASES_PATH)

    assert suite["schema_version"] == 1
    assert suite["suite"] == "c_style_cpp_agent_quality"
    assert suite["cases"][0]["kind"] == "agent_workspace"


def test_legacy_list_suite_is_rejected_with_clear_error(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps([{"kind": "helper"}]), encoding="utf-8")

    with pytest.raises(EvalConfigurationError, match="legacy list format"):
        load_eval_suite(legacy)


def test_snapshot_comparison_ignores_build_artifacts(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "target.cpp").write_text("before\n", encoding="utf-8")
    before = snapshot_workspace(tmp_path)

    (tmp_path / "src" / "target.cpp").write_text("after\n", encoding="utf-8")
    (tmp_path / ".eval_build").mkdir()
    (tmp_path / ".eval_build" / "tests.exe").write_bytes(b"binary")
    after = snapshot_workspace(tmp_path)

    changes = compare_snapshots(before, after)
    assert changes["changed"] == ["src/target.cpp"]


def test_c_style_scanner_ignores_comments_but_detects_code(tmp_path: Path) -> None:
    target = tmp_path / "target.cpp"
    target.write_text("// class and std:: are forbidden in real code\nint value = 1;\n", encoding="utf-8")
    case = {
        "target_files": ["target.cpp"],
        "c_style_rules": {
            "files": ["target.cpp"],
            "forbidden_patterns": [
                {"label": "class", "pattern": r"\bclass\s+[A-Za-z_]"},
                {"label": "STL", "pattern": r"\bstd\s*::"},
            ],
        },
    }
    assert scan_c_style_rules(tmp_path, case) == []

    target.write_text("class Parser {};\n", encoding="utf-8")
    violations = scan_c_style_rules(tmp_path, case)
    assert violations[0]["rule"] == "class"


def test_tool_evidence_tracks_reads_verification_and_repeats() -> None:
    read_spec = {
        "name": "read_file",
        "normalized_arguments": {"path": "SPEC.md"},
        "status": "ok",
    }
    events = [
        read_spec,
        dict(read_spec),
        {
            "name": "read_file",
            "normalized_arguments": {"path": "RULES.md"},
            "status": "ok",
        },
        {
            "name": "exec_command",
            "normalized_arguments": {"cmd": "python run_checks.py"},
            "result_preview": {"ok": True, "returncode": 0},
            "status": "ok",
        },
    ]

    evidence = analyze_tool_evidence(
        events,
        required_context_files=["SPEC.md", "RULES.md"],
        verification_markers=["run_checks.py"],
    )

    assert evidence["context_coverage_complete"] is True
    assert evidence["agent_verification_attempted"] is True
    assert evidence["agent_verification_succeeded"] is True
    assert evidence["repeated_tool_call_count"] == 1


@pytest.mark.parametrize(
    ("returncode", "expected"),
    [(0, "passed"), (1, "failed"), (2, "blocked")],
)
def test_company_verifier_return_codes(tmp_path: Path, returncode: int, expected: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    wrapper = tmp_path / "verify.py"
    _write_exit_script(wrapper, returncode)

    result = execute_authoritative_verifier(
        workspace,
        {"name": "case", "verification": {"script": "run_checks.py", "timeout_sec": 5}},
        verifier_script=str(wrapper),
    )

    assert result["status"] == expected
    assert result["source"] == "company_wrapper"
    assert result["returncode"] == returncode


def test_company_verifier_timeout_is_blocked(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    wrapper = tmp_path / "slow.py"
    _write_exit_script(wrapper, 0, sleep_sec=3.0)

    result = execute_authoritative_verifier(
        workspace,
        {"name": "case", "verification": {"script": "run_checks.py"}},
        verifier_script=str(wrapper),
        timeout_sec=1,
    )

    assert result["status"] == "blocked"
    assert result["returncode"] == 2
    assert "timed out" in result["summary"]


def test_company_verifier_output_redacts_company_paths_and_urls(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    wrapper = tmp_path / "verify.py"
    wrapper.write_text(
        "print(r'C:\\\\Company\\\\Compiler\\\\compiler.exe')\n"
        "print('https://internal.example.invalid/build/123')\n",
        encoding="utf-8",
    )

    result = execute_authoritative_verifier(
        workspace,
        {"name": "case", "verification": {"script": "run_checks.py", "timeout_sec": 5}},
        verifier_script=str(wrapper),
    )

    assert result["status"] == "passed"
    assert "Company" not in result["stdout"]
    assert "internal.example" not in result["stdout"]
    assert "<redacted-path>" in result["stdout"]
    assert "<redacted-url>" in result["stdout"]


def test_aggregate_three_attempts_and_exit_codes() -> None:
    results = [
        {
            "status": "passed",
            "context_and_tools": {"agent_verification_attempted": True},
            "completion_state_accuracy": True,
            "failure_categories": [],
        },
        {
            "status": "failed",
            "context_and_tools": {"agent_verification_attempted": True},
            "completion_state_accuracy": False,
            "failure_categories": ["code_correctness"],
        },
        {
            "status": "blocked",
            "context_and_tools": {"agent_verification_attempted": False},
            "completion_state_accuracy": None,
            "failure_categories": ["environment_blocked"],
        },
    ]

    report = aggregate_eval_results(
        results,
        suite_name="suite",
        cases_path="cases.json",
        provider="openai_compatible",
        model="gpt-5.4",
    )

    assert report["summary"]["passed"] == 1
    assert report["summary"]["failed"] == 1
    assert report["summary"]["blocked"] == 1
    assert report["summary"]["success_rate_percent"] == 33.33
    assert report["summary"]["verification_rate_percent"] == 66.67
    assert report["summary"]["completion_state_accuracy_percent"] == 50.0
    assert report["summary"]["completion_state_accuracy_samples"] == 2
    assert eval_exit_code(report) == 1

    report["summary"]["failed"] = 0
    assert eval_exit_code(report) == 2


class _PassingFakeRuntime:
    def __init__(self, config) -> None:
        self.config = config

    def run(self, *, message, settings, context, progress_cb=None):
        _ = (message, settings, context, progress_cb)
        target = self.config.workspace_root / "src" / "frame_parser.cpp"
        target.write_text(
            '#include "frame_parser.h"\n'
            "FrameParseStatus frame_parse(const unsigned char *frame, unsigned int frame_size, ParsedFrame *out_frame)\n"
            "{\n"
            "    (void)frame;\n"
            "    (void)frame_size;\n"
            "    (void)out_frame;\n"
            "    return FRAME_PARSE_OK;\n"
            "}\n",
            encoding="utf-8",
        )
        reads = [
            {
                "name": "read_file",
                "normalized_arguments": {"path": path},
                "status": "ok",
            }
            for path in (
                "SPEC.md",
                "RULES.md",
                "include/frame_parser.h",
                "reference/checksum_reference.cpp",
            )
        ]
        return {
            "turn_status": "completed",
            "final_answer": "Implemented and checked.",
            "runtime_error": {},
            "pending_user_input": {},
            "pending_approval": {},
            "effective_model": "gpt-test",
            "token_usage": {"llm_calls": 2, "total_tokens": 100},
            "tool_events": [
                *reads,
                {
                    "name": "apply_patch",
                    "normalized_arguments": {"path": "src/frame_parser.cpp"},
                    "result_preview": {"ok": True, "files": [str(target)]},
                    "status": "ok",
                },
                {
                    "name": "exec_command",
                    "normalized_arguments": {"cmd": "python run_checks.py", "cwd": str(self.config.workspace_root)},
                    "result_preview": {"ok": True, "returncode": 0},
                    "status": "ok",
                },
            ],
        }


def test_eval_attempt_uses_fake_runtime_without_live_model(tmp_path: Path) -> None:
    wrapper = tmp_path / "verify.py"
    _write_exit_script(wrapper, 0)
    workspace = tmp_path / "attempt"

    result = run_eval_attempt(
        _case(),
        attempt=1,
        workspace=workspace,
        base_config=load_config(),
        model="gpt-test",
        runtime_factory=_PassingFakeRuntime,
        verifier_script=str(wrapper),
    )

    assert result["status"] == "passed"
    assert result["workspace_changes"]["target_changed"] is True
    assert result["workspace_changes"]["unexpected_changes"] == []
    assert result["context_and_tools"]["context_coverage_complete"] is True
    assert result["verification"]["status"] == "passed"
    assert result["completion_state_accuracy"] is True


def test_eval_attempt_is_blocked_when_authoritative_compiler_is_unavailable(tmp_path: Path) -> None:
    wrapper = tmp_path / "verify.py"
    _write_exit_script(wrapper, 2)

    result = run_eval_attempt(
        _case(),
        attempt=1,
        workspace=tmp_path / "attempt",
        base_config=load_config(),
        model="gpt-test",
        runtime_factory=_PassingFakeRuntime,
        verifier_script=str(wrapper),
    )

    assert result["status"] == "blocked"
    assert result["verification"]["status"] == "blocked"
    assert result["completion_state_accuracy"] is None
    assert result["hard_failures"] == []
    assert result["failure_categories"] == ["environment_blocked"]


CORRECT_IMPLEMENTATION = r'''#include "frame_parser.h"

FrameParseStatus frame_parse(
    const unsigned char *frame,
    unsigned int frame_size,
    ParsedFrame *out_frame
)
{
    unsigned char checksum = 0U;
    unsigned int payload_length = 0U;
    unsigned int expected_size = 0U;
    unsigned int index = 0U;

    if ((frame == 0) || (out_frame == 0)) {
        return FRAME_PARSE_NULL_ARGUMENT;
    }
    if (frame_size < 4U) {
        return FRAME_PARSE_TOO_SHORT;
    }
    if (frame[0] != 0xA5U) {
        return FRAME_PARSE_BAD_PREAMBLE;
    }
    payload_length = (unsigned int)frame[2];
    expected_size = payload_length + 4U;
    if ((payload_length > FRAME_MAX_PAYLOAD) || (frame_size != expected_size)) {
        return FRAME_PARSE_BAD_LENGTH;
    }
    checksum = frame[1];
    checksum = (unsigned char)(checksum ^ frame[2]);
    while (index < payload_length) {
        checksum = (unsigned char)(checksum ^ frame[3U + index]);
        index += 1U;
    }
    if (checksum != frame[3U + payload_length]) {
        return FRAME_PARSE_BAD_CHECKSUM;
    }
    out_frame->command = frame[1];
    out_frame->payload_length = frame[2];
    index = 0U;
    while (index < FRAME_MAX_PAYLOAD) {
        out_frame->payload[index] = (index < payload_length) ? frame[3U + index] : 0U;
        index += 1U;
    }
    return FRAME_PARSE_OK;
}
'''


@pytest.mark.skipif(
    not (shutil.which("cl") or shutil.which("clang++") or shutil.which("g++")),
    reason="No supported local C++ compiler",
)
def test_portable_fixture_compiles_and_tests_known_good_solution(tmp_path: Path) -> None:
    workspace = tmp_path / "fixture"
    shutil.copytree(FIXTURE, workspace)
    (workspace / "src" / "frame_parser.cpp").write_text(CORRECT_IMPLEMENTATION, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(workspace / "run_checks.py")],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "All frame parser tests passed." in completed.stdout


def test_cli_requires_live_and_validate_only_never_calls_provider() -> None:
    validated = subprocess.run(
        [sys.executable, "scripts/run_evals.py", "--validate-only"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert validated.returncode == 0
    assert "Eval suite valid" in validated.stdout

    guarded = subprocess.run(
        [sys.executable, "scripts/run_evals.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert guarded.returncode == 2
    assert "require --live" in guarded.stderr
