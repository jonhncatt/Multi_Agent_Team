from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
root_text = str(ROOT)
if root_text not in sys.path:
    sys.path.insert(0, root_text)


_AMBIENT_VA_ENV: dict[str, str] = {}


def pytest_sessionstart(session: pytest.Session) -> None:
    """Sanitize VA settings before test modules import application globals."""

    _ = session
    _AMBIENT_VA_ENV.clear()
    _AMBIENT_VA_ENV.update(
        {key: value for key, value in os.environ.items() if key.startswith("VA_")}
    )
    for key in list(_AMBIENT_VA_ENV):
        os.environ.pop(key, None)
    os.environ["VA_SKIP_DOTENV"] = "1"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Restore the invoking shell's settings inside the pytest process."""

    _ = (session, exitstatus)
    for key in [item for item in os.environ if item.startswith("VA_")]:
        os.environ.pop(key, None)
    os.environ.update(_AMBIENT_VA_ENV)


@pytest.fixture(autouse=True)
def _isolate_va_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep developer and company VA settings out of deterministic tests."""

    for key in list(os.environ):
        if key.startswith("VA_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VA_SKIP_DOTENV", "1")
    yield
