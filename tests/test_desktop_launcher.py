from __future__ import annotations

from pathlib import Path

import pytest

from desktop.launcher import (
    DesktopLaunchConfig,
    LauncherError,
    build_browser_command,
    build_launch_config,
    build_server_command,
    chrome_preparation_url,
    desktop_instance_guard,
    ensure_desktop_control_token,
    parse_window_size,
    parse_ui_scale,
    read_dotenv,
    restart_server_only,
    resolve_browser_path,
    resolve_project_root,
    resolve_python_command,
    run_desktop,
    start_browser,
    validate_chrome_shell_mode,
    wait_until_stopped,
    write_chrome_preparation_page,
)


def _project_root(tmp_path: Path) -> Path:
    root = tmp_path / "vintage-programmer"
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_text("", encoding="utf-8")
    (root / "desktop").mkdir(parents=True)
    (root / "desktop" / "launcher.py").write_text("", encoding="utf-8")
    (root / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    return root


def test_resolve_project_root_uses_executable_directory_only(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    executable = root / "VintageProgrammer.exe"

    assert resolve_project_root(executable=executable) == root.resolve()


def test_resolve_project_root_does_not_walk_up_from_nested_directory(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    nested = root / "dist"
    nested.mkdir()

    with pytest.raises(LauncherError, match="must be in the Vintage Programmer repository root"):
        resolve_project_root(executable=nested / "VintageProgrammer.exe")


def test_source_launcher_uses_current_directory_only(tmp_path: Path) -> None:
    root = _project_root(tmp_path)

    assert resolve_project_root(cwd=root) == root.resolve()


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


def test_desktop_shell_setting_accepts_legacy_auto_and_chrome_only() -> None:
    assert validate_chrome_shell_mode("") is None
    assert validate_chrome_shell_mode("auto") is None
    assert validate_chrome_shell_mode("chrome") is None
    with pytest.raises(LauncherError, match="Chrome App Mode only"):
        validate_chrome_shell_mode("webview2")


def test_python_resolution_prefers_repository_virtualenv(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    python = root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")

    assert resolve_python_command(root, frozen=True, which=lambda _name: None) == (
        str(python.resolve()),
    )


def test_browser_resolution_finds_google_chrome(tmp_path: Path) -> None:
    program_files = tmp_path / "Program Files"
    chrome = program_files / "Google" / "Chrome" / "Application" / "chrome.exe"
    chrome.parent.mkdir(parents=True)
    chrome.write_bytes(b"")

    resolved = resolve_browser_path(
        platform_name="win32",
        env={"PROGRAMFILES": str(program_files)},
        which=lambda _name: None,
    )

    assert resolved == chrome.resolve()


def test_browser_resolution_does_not_use_edge_as_a_chrome_fallback(tmp_path: Path) -> None:
    program_files = tmp_path / "Program Files"
    edge = program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge.parent.mkdir(parents=True)
    edge.write_bytes(b"")

    with pytest.raises(LauncherError, match="Google Chrome was not found"):
        resolve_browser_path(
            platform_name="win32",
            env={"PROGRAMFILES": str(program_files)},
            which=lambda _name: None,
        )


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
    assert config.chrome_desktop_url == "http://127.0.0.1:9123/?vp_desktop=1&vp_scale=0.8&vp_host=chrome"
    assert config.browser_profile_dir == (
        root / "app" / "data" / "desktop_browser_profile"
    ).resolve()


def test_commands_keep_desktop_shell_outside_agent_runtime(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=(str(root / ".venv" / "Scripts" / "python.exe"),),
        browser_path=tmp_path / "chrome.exe",
        browser_profile_dir=root / "app" / "data" / "desktop_browser_profile",
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
    assert "--app=http://127.0.0.1:8181/?vp_desktop=1&vp_scale=0.8&vp_host=chrome" in browser_command
    assert f"--user-data-dir={root / 'app' / 'data' / 'desktop_browser_profile'}" in browser_command
    assert f"--user-data-dir={root / 'app' / 'data' / 'browser_profile'}" not in browser_command
    assert "--start-maximized" not in browser_command

    initial_command = build_browser_command(config, initialize_window=True)
    assert "--start-maximized" in initial_command
    assert "--window-size=1360,840" in initial_command
    preparing_command = build_browser_command(config, app_url="file:///C:/vp/preparing.html")
    assert "--app=file:///C:/vp/preparing.html" in preparing_command


def test_desktop_control_token_is_stable_and_never_exposed_in_diagnostics(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=("python",),
        browser_path=tmp_path / "chrome.exe",
        browser_profile_dir=root / "browser",
        app_module="app.main:app",
        port=8080,
        startup_timeout_sec=45,
    )

    first = ensure_desktop_control_token(config)
    second = ensure_desktop_control_token(config)

    assert len(first.desktop_control_token) >= 32
    assert second.desktop_control_token == first.desktop_control_token
    assert first.desktop_control_token_path.read_text(encoding="utf-8").strip() == first.desktop_control_token
    assert first.chrome_desktop_url.endswith(f"#vp_control={first.desktop_control_token}")
    assert first.desktop_control_token not in str(first.diagnostics())


def test_chrome_launch_opens_preparing_page_before_backend_is_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project_root(tmp_path)
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=("python",),
        browser_path=tmp_path / "chrome.exe",
        browser_profile_dir=root / "app" / "data" / "desktop_browser_profile",
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
    browser_started: list[tuple[DesktopLaunchConfig, str]] = []
    monkeypatch.setattr("desktop.launcher.health_check", lambda _url: False)
    monkeypatch.setattr("desktop.launcher.start_server", lambda _config: (server, log))
    monkeypatch.setattr("desktop.launcher.wait_until_healthy", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        "desktop.launcher.start_browser",
        lambda browser_config, **kwargs: browser_started.append(
            (browser_config, str(kwargs.get("app_url") or ""))
        ),
    )

    run_desktop(config)

    assert browser_started == [(config, chrome_preparation_url(config))]
    preparation_document = config.desktop_preparing_path.read_text(encoding="utf-8")
    preparation_state = config.desktop_preparing_state_path.read_text(encoding="utf-8")
    assert "Preparing…" in preparation_document
    assert config.desktop_preparing_state_path.name in preparation_document
    assert config.chrome_desktop_url in preparation_state
    assert "window.location.replace" in preparation_state
    assert server.terminated is False
    assert log.closed is True


def test_chrome_preparing_page_uses_brand_icon_without_translation_prompt(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    icon = root / "app" / "static" / "assets" / "vintage_programmer.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"png")
    favicon = icon.with_suffix(".ico")
    favicon.write_bytes(b"ico")
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=("python",),
        browser_path=tmp_path / "chrome.exe",
        browser_profile_dir=root / "browser",
        app_module="app.main:app",
        port=8080,
        startup_timeout_sec=45,
    )

    path = write_chrome_preparation_page(config, state="preparing")
    document = path.read_text(encoding="utf-8")

    assert path == config.desktop_preparing_path
    assert chrome_preparation_url(config).startswith("file://")
    assert "Preparing…" in document
    assert "Vintage Programmer will open automatically when ready." not in document
    assert "正在启动本地工作区" not in document
    assert '<meta name="google" content="notranslate">' in document
    assert 'translate="no" class="notranslate"' in document
    assert '<p id="preparingDetail" hidden></p>' in document
    assert icon.resolve().as_uri() in document
    assert favicon.resolve().as_uri() in document
    assert "Date.now()" in document
    assert config.desktop_preparing_state_path.read_text(encoding="utf-8") == (
        "window.__VP_PREPARING_STATE__='preparing';"
    )


def test_chrome_preparing_page_reports_backend_start_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project_root(tmp_path)
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=("python",),
        browser_path=tmp_path / "chrome.exe",
        browser_profile_dir=root / "browser",
        app_module="app.main:app",
        port=8080,
        startup_timeout_sec=45,
    )

    class _Process:
        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            return None

        def wait(self, timeout: int) -> None:
            return None

    class _Log:
        def close(self) -> None:
            return None

    monkeypatch.setattr("desktop.launcher.health_check", lambda _url: False)
    monkeypatch.setattr("desktop.launcher.start_browser", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("desktop.launcher.start_server", lambda _config: (_Process(), _Log()))
    monkeypatch.setattr("desktop.launcher.wait_until_healthy", lambda *_args, **_kwargs: False)

    with pytest.raises(LauncherError, match="did not start"):
        run_desktop(config)

    state_script = config.desktop_preparing_state_path.read_text(encoding="utf-8")
    assert "vpPreparingFailed" in state_script
    assert "did not start" in state_script


def test_chrome_opens_final_page_immediately_when_backend_is_already_healthy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project_root(tmp_path)
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=("python",),
        browser_path=tmp_path / "chrome.exe",
        browser_profile_dir=root / "browser",
        app_module="app.main:app",
        port=8080,
        startup_timeout_sec=45,
    )
    opened: list[dict[str, object]] = []
    monkeypatch.setattr("desktop.launcher.health_check", lambda _url: True)
    monkeypatch.setattr("desktop.launcher.focus_existing_desktop_window", lambda: False)
    monkeypatch.setattr(
        "desktop.launcher.start_browser",
        lambda _config, **kwargs: opened.append(dict(kwargs)) or object(),
    )

    run_desktop(config)

    assert opened == [{}]
    assert config.desktop_preparing_path.exists() is False


def test_chrome_reuses_existing_window_when_backend_is_healthy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project_root(tmp_path)
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=("python",),
        browser_path=tmp_path / "chrome.exe",
        browser_profile_dir=root / "browser",
        app_module="app.main:app",
        port=8080,
        startup_timeout_sec=45,
    )
    focused: list[bool] = []
    monkeypatch.setattr("desktop.launcher.health_check", lambda _url: True)
    monkeypatch.setattr(
        "desktop.launcher.focus_existing_desktop_window",
        lambda: focused.append(True) or True,
    )
    monkeypatch.setattr(
        "desktop.launcher.start_browser",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("existing window must be reused")
        ),
    )

    run_desktop(config)

    assert focused == [True]


def test_wait_until_stopped_returns_after_backend_becomes_unreachable() -> None:
    probes = iter([True, True, False])

    assert wait_until_stopped(
        "http://127.0.0.1:8080/api/health",
        timeout_sec=1,
        probe=lambda _url: next(probes),
    ) is True


def test_restart_server_only_waits_for_shutdown_then_starts_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project_root(tmp_path)
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=("python",),
        browser_path=tmp_path / "chrome.exe",
        browser_profile_dir=root / "browser",
        app_module="app.main:app",
        port=8080,
        startup_timeout_sec=45,
    )
    events: list[str] = []

    class _Log:
        def close(self) -> None:
            events.append("log_closed")

    monkeypatch.setattr(
        "desktop.launcher.wait_until_stopped",
        lambda *_args, **_kwargs: events.append("stopped") or True,
    )
    monkeypatch.setattr("desktop.launcher.health_check", lambda _url: False)
    monkeypatch.setattr(
        "desktop.launcher.start_server",
        lambda _config: (events.append("started") or object(), _Log()),
    )
    monkeypatch.setattr(
        "desktop.launcher.wait_until_healthy",
        lambda *_args, **_kwargs: events.append("healthy") or True,
    )

    restart_server_only(config)

    assert events == ["stopped", "started", "healthy", "log_closed"]


def test_browser_process_is_detached_and_initial_size_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project_root(tmp_path)
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=("python",),
        browser_path=tmp_path / "chrome",
        browser_profile_dir=root / "app" / "data" / "desktop_browser_profile",
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


def test_desktop_single_instance_guard_focuses_existing_window() -> None:
    focused: list[bool] = []
    closed: list[object] = []

    with desktop_instance_guard(
        platform_name="win32",
        create_mutex=lambda *_args: 42,
        get_last_error=lambda: 183,
        close_handle=lambda handle: closed.append(handle),
        focus_existing=lambda: focused.append(True) or True,
    ) as primary:
        assert primary is False

    assert focused == [True]
    assert closed == [42]
