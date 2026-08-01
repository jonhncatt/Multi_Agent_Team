from __future__ import annotations

from pathlib import Path

import pytest

from desktop.launcher import (
    DesktopLaunchConfig,
    LauncherError,
    build_browser_command,
    build_launch_config,
    build_server_command,
    parse_shell_mode,
    parse_window_size,
    parse_ui_scale,
    read_dotenv,
    resolve_browser_path,
    resolve_project_root,
    resolve_python_command,
    run_desktop,
    should_try_webview2,
    start_browser,
)
from desktop.webview_host import WebViewHostError


def _project_root(tmp_path: Path) -> Path:
    root = tmp_path / "vintage-programmer"
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_text("", encoding="utf-8")
    (root / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    return root


def test_resolve_project_root_walks_up_from_launcher_location(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    nested = root / "desktop" / "windows"
    nested.mkdir(parents=True)

    assert resolve_project_root(cwd=nested, module_file=nested / "launcher.py") == root.resolve()


def test_resolve_project_root_rejects_unrelated_explicit_directory(tmp_path: Path) -> None:
    with pytest.raises(LauncherError, match="not a Vintage Programmer checkout"):
        resolve_project_root(tmp_path)


def test_read_dotenv_matches_repository_style_values(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# comment\nVP_APP_PORT='8123'\nexport VP_APP_MODULE=sample.main:app # inline\n",
        encoding="utf-8",
    )

    assert read_dotenv(dotenv) == {
        "VP_APP_PORT": "8123",
        "VP_APP_MODULE": "sample.main:app",
    }


def test_parse_window_size_accepts_comma_or_x_and_rejects_tiny_windows() -> None:
    assert parse_window_size("1360,840") == (1360, 840)
    assert parse_window_size("1440x900") == (1440, 900)
    with pytest.raises(LauncherError, match="between 900x600"):
        parse_window_size("800,500")


def test_parse_ui_scale_accepts_desktop_density_and_rejects_extremes() -> None:
    assert parse_ui_scale("0.8") == 0.8
    assert parse_ui_scale("1") == 1.0
    with pytest.raises(LauncherError, match="between 0.65 and 1.25"):
        parse_ui_scale("0.5")


def test_parse_shell_mode_accepts_supported_desktop_hosts() -> None:
    assert parse_shell_mode("") == "auto"
    assert parse_shell_mode("WebView2") == "webview2"
    assert parse_shell_mode("chrome") == "chrome"
    with pytest.raises(LauncherError, match="auto, webview2, or chrome"):
        parse_shell_mode("electron")


def test_python_resolution_prefers_repository_virtualenv(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    python = root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")

    assert resolve_python_command(root, frozen=True, which=lambda _name: None) == (
        str(python.resolve()),
    )


def test_browser_resolution_prefers_chrome_before_edge(tmp_path: Path) -> None:
    program_files = tmp_path / "Program Files"
    chrome = program_files / "Google" / "Chrome" / "Application" / "chrome.exe"
    edge = program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    chrome.parent.mkdir(parents=True)
    edge.parent.mkdir(parents=True)
    chrome.write_bytes(b"")
    edge.write_bytes(b"")

    resolved = resolve_browser_path(
        platform_name="win32",
        env={"PROGRAMFILES": str(program_files)},
        which=lambda _name: None,
    )

    assert resolved == chrome.resolve()


def test_desktop_and_agent_profiles_cannot_be_shared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _project_root(tmp_path)
    python = root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    browser = tmp_path / "chrome.exe"
    browser.write_bytes(b"")
    (root / ".env").write_text(
        "VP_BROWSER_USER_DATA_DIR=app/data/browser_profile\n"
        "VP_DESKTOP_BROWSER_USER_DATA_DIR=app/data/browser_profile\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("desktop.launcher.sys.frozen", True, raising=False)

    with pytest.raises(LauncherError, match="cannot share a live browser profile"):
        build_launch_config(project_root=root, browser_path=str(browser), env={})


def test_chrome_and_webview_profiles_cannot_be_shared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project_root(tmp_path)
    python = root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    browser = tmp_path / "chrome.exe"
    browser.write_bytes(b"")
    (root / ".env").write_text(
        "VP_DESKTOP_BROWSER_USER_DATA_DIR=app/data/desktop_profile\n"
        "VP_DESKTOP_WEBVIEW2_USER_DATA_DIR=app/data/desktop_profile\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("desktop.launcher.sys.frozen", True, raising=False)

    with pytest.raises(LauncherError, match="must use different directories"):
        build_launch_config(project_root=root, browser_path=str(browser), env={})


def test_windows_auto_mode_does_not_require_chrome_when_webview2_is_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project_root(tmp_path)
    python = root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    monkeypatch.setattr("desktop.launcher.sys.platform", "win32")
    monkeypatch.setattr("desktop.launcher.sys.frozen", True, raising=False)
    monkeypatch.setattr(
        "desktop.launcher.resolve_browser_path",
        lambda **_kwargs: (_ for _ in ()).throw(LauncherError("browser missing")),
    )

    config = build_launch_config(project_root=root, env={"VP_DESKTOP_SHELL": "auto"})

    assert config.browser_path is None
    assert should_try_webview2(config, platform_name="win32") is True


def test_launch_config_uses_same_dotenv_port_as_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project_root(tmp_path)
    python = root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    browser = tmp_path / "chrome.exe"
    browser.write_bytes(b"")
    (root / ".env").write_text("VP_APP_PORT=9123\n", encoding="utf-8")
    monkeypatch.setattr("desktop.launcher.sys.frozen", True, raising=False)

    config = build_launch_config(
        project_root=root,
        browser_path=str(browser),
        env={"VP_APP_PORT": "8123"},
    )

    assert config.port == 9123
    assert config.app_url == "http://127.0.0.1:9123"
    assert config.desktop_url == "http://127.0.0.1:9123/?vp_desktop=1&vp_scale=0.8"
    assert config.shell_mode == "auto"
    assert config.browser_profile_dir == (
        root / "app" / "data" / "desktop_browser_profile"
    ).resolve()
    assert config.webview_profile_dir == (
        root / "app" / "data" / "desktop_webview2_profile"
    ).resolve()


def test_commands_keep_desktop_shell_outside_agent_runtime(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=(str(root / ".venv" / "Scripts" / "python.exe"),),
        browser_path=tmp_path / "chrome.exe",
        browser_profile_dir=root / "app" / "data" / "desktop_browser_profile",
        webview_profile_dir=root / "app" / "data" / "desktop_webview2_profile",
        app_module="app.main:app",
        port=8181,
        startup_timeout_sec=45,
    )

    assert build_server_command(config) == [
        str(root / ".venv" / "Scripts" / "python.exe"),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8181",
    ]
    browser_command = build_browser_command(config)
    assert "--app=http://127.0.0.1:8181/?vp_desktop=1&vp_scale=0.8" in browser_command
    assert f"--user-data-dir={root / 'app' / 'data' / 'desktop_browser_profile'}" in browser_command
    assert f"--user-data-dir={root / 'app' / 'data' / 'browser_profile'}" not in browser_command
    assert "--start-maximized" not in browser_command

    initial_command = build_browser_command(config, initialize_window=True)
    assert "--start-maximized" in initial_command
    assert "--window-size=1360,840" in initial_command


def test_successful_launch_does_not_terminate_owned_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project_root(tmp_path)
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=("python",),
        browser_path=tmp_path / "chrome.exe",
        browser_profile_dir=root / "app" / "data" / "desktop_browser_profile",
        webview_profile_dir=root / "app" / "data" / "desktop_webview2_profile",
        app_module="app.main:app",
        port=8080,
        startup_timeout_sec=45,
    )

    class _Process:
        terminated = False

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            self.terminated = True

    class _Log:
        closed = False

        def close(self) -> None:
            self.closed = True

    server = _Process()
    log = _Log()
    browser_started: list[DesktopLaunchConfig] = []
    monkeypatch.setattr("desktop.launcher.health_check", lambda _url: False)
    monkeypatch.setattr("desktop.launcher.start_server", lambda _config: (server, log))
    monkeypatch.setattr("desktop.launcher.wait_until_healthy", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        "desktop.launcher.start_browser",
        lambda browser_config: browser_started.append(browser_config),
    )

    run_desktop(config)

    assert browser_started == [config]
    assert server.terminated is False
    assert log.closed is True


def test_browser_process_is_detached_and_initial_size_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project_root(tmp_path)
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=("python",),
        browser_path=tmp_path / "chrome",
        browser_profile_dir=root / "app" / "data" / "desktop_browser_profile",
        webview_profile_dir=root / "app" / "data" / "desktop_webview2_profile",
        app_module="app.main:app",
        port=8080,
        startup_timeout_sec=45,
    )
    popen_calls: list[tuple[list[str], dict[str, object]]] = []
    process = object()

    def _popen(command: list[str], **kwargs: object) -> object:
        popen_calls.append((command, kwargs))
        return process

    monkeypatch.setattr("desktop.launcher.subprocess.Popen", _popen)
    monkeypatch.setattr("desktop.launcher.os.name", "posix")

    assert start_browser(config) is process
    assert "--start-maximized" in popen_calls[0][0]
    assert popen_calls[0][1]["start_new_session"] is True
    assert config.window_initialized_marker.read_text(encoding="utf-8") == "1\n"


def test_windows_auto_mode_prefers_webview2_and_chrome_mode_does_not(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=("python",),
        browser_path=tmp_path / "chrome.exe",
        browser_profile_dir=root / "app" / "data" / "desktop_browser_profile",
        webview_profile_dir=root / "app" / "data" / "desktop_webview2_profile",
        app_module="app.main:app",
        port=8080,
        startup_timeout_sec=45,
    )

    assert should_try_webview2(config, platform_name="win32") is True
    assert should_try_webview2(config, platform_name="darwin") is False
    assert should_try_webview2(
        DesktopLaunchConfig(
            project_root=config.project_root,
            python_command=config.python_command,
            browser_path=config.browser_path,
            browser_profile_dir=config.browser_profile_dir,
            webview_profile_dir=config.webview_profile_dir,
            app_module=config.app_module,
            port=config.port,
            startup_timeout_sec=config.startup_timeout_sec,
            shell_mode="chrome",
        ),
        platform_name="win32",
    ) is False


def test_webview2_failure_falls_back_to_chrome_without_stopping_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project_root(tmp_path)
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=("python",),
        browser_path=tmp_path / "chrome.exe",
        browser_profile_dir=root / "app" / "data" / "desktop_browser_profile",
        webview_profile_dir=root / "app" / "data" / "desktop_webview2_profile",
        app_module="app.main:app",
        port=8080,
        startup_timeout_sec=45,
    )

    class _Process:
        terminated = False

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            self.terminated = True

    class _Log:
        closed = False

        def close(self) -> None:
            self.closed = True

    server = _Process()
    log = _Log()
    browser_started: list[DesktopLaunchConfig] = []
    monkeypatch.setattr("desktop.launcher.health_check", lambda _url: False)
    monkeypatch.setattr("desktop.launcher.start_server", lambda _config: (server, log))
    monkeypatch.setattr("desktop.launcher.wait_until_healthy", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("desktop.launcher.should_try_webview2", lambda _config: True)
    monkeypatch.setattr(
        "desktop.launcher.start_webview2",
        lambda _config: (_ for _ in ()).throw(WebViewHostError("runtime missing")),
    )
    monkeypatch.setattr(
        "desktop.launcher.start_browser",
        lambda browser_config: browser_started.append(browser_config),
    )

    run_desktop(config)

    assert browser_started == [config]
    assert server.terminated is False
    assert log.closed is True
    assert "using Chrome App Mode" in config.log_path.read_text(encoding="utf-8")


def test_webview2_window_close_does_not_stop_owned_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project_root(tmp_path)
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=("python",),
        browser_path=tmp_path / "chrome.exe",
        browser_profile_dir=root / "app" / "data" / "desktop_browser_profile",
        webview_profile_dir=root / "app" / "data" / "desktop_webview2_profile",
        app_module="app.main:app",
        port=8080,
        startup_timeout_sec=45,
    )

    class _Process:
        terminated = False

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            self.terminated = True

    class _Log:
        closed = False

        def close(self) -> None:
            self.closed = True

    server = _Process()
    log = _Log()
    native_started: list[DesktopLaunchConfig] = []
    monkeypatch.setattr("desktop.launcher.health_check", lambda _url: False)
    monkeypatch.setattr("desktop.launcher.start_server", lambda _config: (server, log))
    monkeypatch.setattr("desktop.launcher.wait_until_healthy", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("desktop.launcher.should_try_webview2", lambda _config: True)
    monkeypatch.setattr(
        "desktop.launcher.start_webview2",
        lambda native_config: native_started.append(native_config),
    )

    run_desktop(config)

    assert native_started == [config]
    assert server.terminated is False
    assert log.closed is True
