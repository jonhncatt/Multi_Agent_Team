from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import time
from typing import Any, Iterator


def _now_epoch_ms() -> int:
    return int(time.time() * 1000)


@dataclass(slots=True)
class PhaseTimer:
    started_at_ms: int = field(default_factory=_now_epoch_ms)
    _started_perf: float = field(default_factory=time.perf_counter)
    offset_base_ms: int = 0
    _phases: dict[str, int] = field(default_factory=dict)

    def elapsed_ms(self) -> int:
        return max(0, int((time.perf_counter() - self._started_perf) * 1000))

    def record_duration_ms(self, name: str, duration_ms: Any) -> None:
        normalized = str(name or "").strip()
        if not normalized:
            return
        try:
            value = int(duration_ms)
        except Exception:
            return
        self._phases[normalized] = max(0, value)

    def record_offset_ms(self, name: str, *, perf_value: float | None = None, if_missing: bool = False) -> None:
        normalized = str(name or "").strip()
        if not normalized:
            return
        if if_missing and normalized in self._phases:
            return
        target = perf_value if perf_value is not None else time.perf_counter()
        self._phases[normalized] = max(0, int(self.offset_base_ms) + int((target - self._started_perf) * 1000))

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.record_duration_ms(name, int((time.perf_counter() - started) * 1000))

    def snapshot(self, *, total_key: str = "total_ms", include_started_at: bool = False) -> dict[str, int]:
        payload = dict(self._phases)
        payload[str(total_key or "total_ms")] = self.elapsed_ms()
        if include_started_at:
            payload["started_at_ms"] = max(0, int(self.started_at_ms))
        return payload
