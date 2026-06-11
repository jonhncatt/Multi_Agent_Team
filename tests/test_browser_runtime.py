from __future__ import annotations

import json
from pathlib import Path
import threading

from app.browser_runtime import BrowserToolManager


class _FakePage:
    def __init__(self) -> None:
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True


class _FakeContext:
    def __init__(self) -> None:
        self.pages = []

    async def new_page(self) -> _FakePage:
        page = _FakePage()
        self.pages.append(page)
        return page

    async def close(self) -> None:
        pass


class _FakeChromium:
    def __init__(self) -> None:
        self.persistent_calls: list[dict[str, object]] = []

    async def launch_persistent_context(self, user_data_dir: str, **kwargs: object) -> _FakeContext:
        self.persistent_calls.append({"user_data_dir": user_data_dir, **kwargs})
        return _FakeContext()


class _FakePlaywright:
    def __init__(self) -> None:
        self.chromium = _FakeChromium()
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class _FakeAsyncPlaywright:
    def __init__(self, playwright: _FakePlaywright) -> None:
        self._playwright = playwright

    def __call__(self) -> "_FakeAsyncPlaywright":
        return self

    async def start(self) -> _FakePlaywright:
        return self._playwright


def test_chrome_profile_mode_launches_installed_chrome_with_persistent_profile(tmp_path: Path) -> None:
    fake_playwright = _FakePlaywright()
    profile_dir = tmp_path / "profile"
    manager = BrowserToolManager(
        artifacts_dir=tmp_path / "artifacts",
        mode="chrome_profile",
        channel="chrome",
        headless=False,
        user_data_dir=profile_dir,
        proxy_server="http://proxy.example:8080",
        ignore_https_errors=True,
        chromium_sandbox=True,
    )
    manager._import_playwright = lambda: (_FakeAsyncPlaywright(fake_playwright), TimeoutError)  # type: ignore[method-assign]

    manager._run_async(lambda: manager._ensure_session("session-a"))  # noqa: SLF001 - focused launch regression

    assert fake_playwright.chromium.persistent_calls == [
        {
            "user_data_dir": str(profile_dir.resolve()),
            "viewport": {"width": 1440, "height": 960},
            "locale": "zh-CN",
            "ignore_https_errors": True,
            "proxy": {"server": "http://proxy.example:8080"},
            "headless": False,
            "chromium_sandbox": True,
            "channel": "chrome",
        }
    ]


def test_chrome_profile_disables_password_manager_preferences(tmp_path: Path) -> None:
    fake_playwright = _FakePlaywright()
    profile_dir = tmp_path / "profile"
    manager = BrowserToolManager(
        artifacts_dir=tmp_path / "artifacts",
        mode="chrome_profile",
        channel="chrome",
        headless=False,
        user_data_dir=profile_dir,
        disable_password_manager=True,
    )
    manager._import_playwright = lambda: (_FakeAsyncPlaywright(fake_playwright), TimeoutError)  # type: ignore[method-assign]

    manager._run_async(lambda: manager._ensure_session("session-a"))  # noqa: SLF001 - focused launch regression

    preferences = json.loads((profile_dir / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert preferences["credentials_enable_service"] is False
    assert preferences["profile"]["password_manager_enabled"] is False
    assert preferences["profile"]["password_manager_leak_detection"] is False


def test_closed_browser_page_reopens_with_same_profile(tmp_path: Path) -> None:
    fake_playwright = _FakePlaywright()
    profile_dir = tmp_path / "profile"
    manager = BrowserToolManager(
        artifacts_dir=tmp_path / "artifacts",
        mode="chrome_profile",
        channel="chrome",
        headless=False,
        user_data_dir=profile_dir,
    )
    manager._import_playwright = lambda: (_FakeAsyncPlaywright(fake_playwright), TimeoutError)  # type: ignore[method-assign]

    first = manager._run_async(lambda: manager._ensure_session("session-a"))  # noqa: SLF001
    manager._run_async(first.page.close)  # noqa: SLF001
    second = manager._run_async(lambda: manager._ensure_session("session-a"))  # noqa: SLF001

    assert second is not first
    assert len(fake_playwright.chromium.persistent_calls) == 2
    assert {
        str(item["user_data_dir"])
        for item in fake_playwright.chromium.persistent_calls
    } == {str(profile_dir.resolve())}


def test_browser_operations_are_dispatched_to_one_worker_thread(tmp_path: Path) -> None:
    manager = BrowserToolManager(artifacts_dir=tmp_path / "artifacts")

    thread_ids = [
        manager._run_async(lambda: _thread_id()),  # noqa: SLF001 - worker threading regression
        manager._run_async(lambda: _thread_id()),  # noqa: SLF001 - worker threading regression
    ]

    assert thread_ids[0] == thread_ids[1]
    assert thread_ids[0] != threading.get_ident()


async def _thread_id() -> int:
    return threading.get_ident()
