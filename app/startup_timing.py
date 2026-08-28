from __future__ import annotations

import json
import time
from typing import Callable


class StartupTimer:
    """Emit a small number of structured milestones during backend import."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sink: Callable[[str], None] | None = None,
    ) -> None:
        self._clock = clock
        self._wall_clock = wall_clock
        self._sink = sink or (lambda line: print(line, flush=True))
        self._started_at = clock()
        self._last_mark_at = self._started_at

    @staticmethod
    def _milliseconds(seconds: float) -> int:
        return max(0, int(round(seconds * 1000)))

    def mark(self, phase: str, **fields: object) -> None:
        now = self._clock()
        payload = {
            "event": "backend_startup_phase",
            "phase": str(phase or "unknown"),
            "phase_ms": self._milliseconds(now - self._last_mark_at),
            "elapsed_ms": self._milliseconds(now - self._started_at),
            **fields,
        }
        timestamp = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(self._wall_clock()),
        )
        self._sink(
            f"{timestamp} [backend-startup] "
            f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        )
        self._last_mark_at = now
