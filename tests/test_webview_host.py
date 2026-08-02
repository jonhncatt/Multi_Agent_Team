from __future__ import annotations

from pathlib import Path

import pytest

from desktop.webview_host import (
    APP_USER_MODEL_ID,
    WebViewHostError,
    bundled_asset_path,
    close_dialog_copy,
    open_webview2_window,
    probe_webview2_host,
    set_windows_app_identity,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class _Event:
    def __init__(self) -> None:
        self.handlers: list[object] = []

    def __iadd__(self, handler: object):
        self.handlers.append(handler)
        return self

    def fire(self, *args: object) -> list[object]:
        return [handler(*args) for handler in self.handlers]  # type: ignore[operator]


class _Events:
    def __init__(self) -> None:
        self.initialized = _Event()
        self.before_show = _Event()
        self.closing = _Event()


class _Window:
    def __init__(self) -> None:
        self.events = _Events()
        self.native = object()


class _FakeWebView:
    def __init__(self, renderer: str = "edgechromium") -> None:
        self.renderer = renderer
        self.settings: dict[str, object] = {}
        self.window = _Window()
        self.create_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.start_kwargs: dict[str, object] = {}

    def create_window(self, *args: object, **kwargs: object) -> _Window:
        self.create_calls.append((args, kwargs))
        return self.window

    def start(self, **kwargs: object) -> None:
        self.start_kwargs = kwargs
        results = self.window.events.initialized.fire(self.renderer)
        if all(result is not False for result in results):
            self.window.events.before_show.fire()


def test_windows_app_identity_uses_stable_vp_identifier() -> None:
    calls: list[str] = []

    set_windows_app_identity(platform_name="win32", setter=lambda value: calls.append(value) or 0)

    assert calls == [APP_USER_MODEL_ID]


def test_active_close_dialog_has_only_stop_exit_and_cancel_choices() -> None:
    message, stop_label, cancel_label = close_dialog_copy("zh-CN", 2)

    assert "2 个任务" in message
    assert stop_label == "停止任务并完全退出"
    assert cancel_label == "取消关闭"


def test_bundled_asset_path_falls_back_to_repository_asset(tmp_path: Path) -> None:
    expected = tmp_path / "desktop" / "windows" / "assets" / "vintage_programmer.ico"

    assert bundled_asset_path(
        tmp_path,
        "desktop/windows/assets/vintage_programmer.ico",
    ) == expected


def test_native_host_opens_persistent_maximized_edgechromium_window(tmp_path: Path) -> None:
    icon = tmp_path / "desktop" / "windows" / "assets" / "vintage_programmer.ico"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"icon")
    fake = _FakeWebView()
    identities: list[str] = []
    applied_icons: list[Path] = []

    open_webview2_window(
        url="http://127.0.0.1:8080/?vp_desktop=1&vp_scale=0.8",
        project_root=tmp_path,
        profile_dir=tmp_path / "profile",
        width=1360,
        height=840,
        platform_name="win32",
        webview_module=fake,
        app_identity_setter=lambda value: identities.append(value) or 0,
        icon_applier=lambda _window, path: applied_icons.append(path),
    )

    assert identities == [APP_USER_MODEL_ID]
    assert fake.settings["ALLOW_DOWNLOADS"] is True
    assert fake.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is True
    assert fake.create_calls[0][0] == (
        "Vintage Programmer",
        "http://127.0.0.1:8080/?vp_desktop=1&vp_scale=0.8",
    )
    assert fake.create_calls[0][1]["maximized"] is True
    assert fake.create_calls[0][1]["min_size"] == (900, 600)
    assert fake.start_kwargs == {
        "gui": "edgechromium",
        "private_mode": False,
        "storage_path": str(tmp_path / "profile"),
        "icon": str(icon),
    }
    assert applied_icons == [icon]


def test_native_host_closing_event_can_cancel_or_allow_window_close(tmp_path: Path) -> None:
    fake = _FakeWebView()
    decisions = iter((False, True))
    owners: list[object] = []

    open_webview2_window(
        url="http://127.0.0.1:8080",
        project_root=tmp_path,
        profile_dir=tmp_path / "profile",
        width=1360,
        height=840,
        platform_name="win32",
        webview_module=fake,
        app_identity_setter=lambda _value: 0,
        closing_handler=lambda owner: owners.append(owner) or next(decisions),
    )

    assert fake.window.events.closing.fire() == [False]
    assert fake.window.events.closing.fire() == [True]
    assert owners == [fake.window, fake.window]


def test_native_host_rejects_mshtml_so_launcher_can_fallback(tmp_path: Path) -> None:
    fake = _FakeWebView(renderer="mshtml")

    with pytest.raises(WebViewHostError, match="WebView2 Runtime is unavailable"):
        open_webview2_window(
            url="http://127.0.0.1:8080",
            project_root=tmp_path,
            profile_dir=tmp_path / "profile",
            width=1360,
            height=840,
            platform_name="win32",
            webview_module=fake,
            app_identity_setter=lambda _value: 0,
        )


def test_probe_reports_non_windows_without_importing_native_dependencies() -> None:
    assert probe_webview2_host(platform_name="darwin") == {
        "available": False,
        "renderer": "",
        "reason": "WebView2 is available only on Windows.",
    }


def test_windows_build_embeds_multisize_vp_icon_and_webview_host() -> None:
    asset_dir = REPO_ROOT / "desktop" / "windows" / "assets"
    icon = (asset_dir / "vintage_programmer.ico").read_bytes()
    png = (asset_dir / "vintage_programmer.png").read_bytes()
    svg = (asset_dir / "vintage_programmer.svg").read_text(encoding="utf-8")
    build_script = (REPO_ROOT / "desktop" / "windows" / "build.ps1").read_text(
        encoding="utf-8"
    )
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "windows-desktop-launcher.yml"
    ).read_text(encoding="utf-8")
    requirements = (
        REPO_ROOT / "desktop" / "windows" / "requirements-build.txt"
    ).read_text(encoding="utf-8")

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert icon[:4] == b"\x00\x00\x01\x00"
    assert int.from_bytes(icon[4:6], "little") == 7
    assert "#f37021" in svg
    assert "--icon desktop\\windows\\assets\\vintage_programmer.ico" in build_script
    assert "--icon desktop/windows/assets/vintage_programmer.ico" in workflow
    assert "Start-Process" in workflow
    assert "-Wait" in workflow
    assert "if ($launcher.ExitCode -ne 0)" in workflow
    assert "pywebview==6.2.1" in requirements
