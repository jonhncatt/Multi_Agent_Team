from __future__ import annotations

import json

from app.startup_timing import StartupTimer


def test_startup_timer_emits_compact_phase_and_total_timings() -> None:
    clock_values = iter([10.0, 10.125, 10.5])
    lines: list[str] = []
    timer = StartupTimer(
        clock=lambda: next(clock_values),
        wall_clock=lambda: 0.0,
        sink=lines.append,
    )

    timer.mark("dependencies_imported")
    timer.mark("runtime_initialized", migrated=2)

    first = json.loads(lines[0].split("] ", 1)[1])
    second = json.loads(lines[1].split("] ", 1)[1])
    assert first == {
        "elapsed_ms": 125,
        "event": "backend_startup_phase",
        "phase": "dependencies_imported",
        "phase_ms": 125,
    }
    assert second == {
        "elapsed_ms": 500,
        "event": "backend_startup_phase",
        "migrated": 2,
        "phase": "runtime_initialized",
        "phase_ms": 375,
    }
