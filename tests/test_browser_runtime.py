from __future__ import annotations

from pathlib import Path
import threading

from app.browser_runtime import BrowserToolManager


class _FakePage:
    def __init__(self) -> None:
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class _FakeContext:
    def __init__(self) -> None:
        self.pages = []

    def new_page(self) -> _FakePage:
        page = _FakePage()
        self.pages.append(page)
        return page

    def close(self) -> None:
        pass


class _FakeChromium:
    def __init__(self) -> None:
        self.persistent_calls: list[dict[str, object]] = []

    def launch_persistent_context(self, user_data_dir: str, **kwargs: object) -> _FakeContext:
        self.persistent_calls.append({"user_data_dir": user_data_dir, **kwargs})
        return _FakeContext()


class _FakePlaywright:
    def __init__(self) -> None:
        self.chromium = _FakeChromium()
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _FakeSyncPlaywright:
    def __init__(self, playwright: _FakePlaywright) -> None:
        self._playwright = playwright

    def __call__(self) -> "_FakeSyncPlaywright":
        return self

    def start(self) -> _FakePlaywright:
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
    manager._import_playwright = lambda: (_FakeSyncPlaywright(fake_playwright), TimeoutError)  # type: ignore[method-assign]

    manager._ensure_session("session-a")  # noqa: SLF001 - focused launch regression

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
    manager._import_playwright = lambda: (_FakeSyncPlaywright(fake_playwright), TimeoutError)  # type: ignore[method-assign]

    first = manager._ensure_session("session-a")  # noqa: SLF001 - focused launch regression
    first.page.close()
    second = manager._ensure_session("session-a")  # noqa: SLF001 - focused launch regression

    assert second is not first
    assert len(fake_playwright.chromium.persistent_calls) == 2
    assert {
        str(item["user_data_dir"])
        for item in fake_playwright.chromium.persistent_calls
    } == {str(profile_dir.resolve())}


def test_browser_operations_are_dispatched_to_one_worker_thread(tmp_path: Path) -> None:
    manager = BrowserToolManager(artifacts_dir=tmp_path / "artifacts")

    thread_ids = [
        manager._run_on_worker(lambda: threading.get_ident()),  # noqa: SLF001 - worker threading regression
        manager._run_on_worker(lambda: threading.get_ident()),  # noqa: SLF001 - worker threading regression
    ]

    assert thread_ids[0] == thread_ids[1]
    assert thread_ids[0] != threading.get_ident()
