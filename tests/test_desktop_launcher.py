from __future__ import annotations

import ctypes
from pathlib import Path
import sys

import pytest

from desktop.launcher import (
    APP_TITLE,
    WINDOWS_APP_USER_MODEL_ID,
    DesktopLaunchConfig,
    LauncherError,
    _set_windows_taskbar_window_properties,
    build_browser_command,
    build_launch_config,
    build_server_command,
    bind_windows_taskbar_identity,
    chrome_preparation_url,
    desktop_instance_guard,
    ensure_desktop_control_token,
    find_windows_vp_window,
    parse_window_size,
    parse_ui_scale,
    read_dotenv,
    restart_server_only,
    reset_launcher_log_if_oversized,
    resolve_browser_path,
    resolve_project_root,
    resolve_python_command,
    run_desktop,
    set_windows_process_app_id,
    start_browser,
    validate_chrome_shell_mode,
    wait_until_stopped,
    write_chrome_preparation_page,
    windows_taskbar_relaunch_metadata,
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


def test_launcher_log_is_cleared_without_backup_when_size_limit_is_exceeded(tmp_path: Path) -> None:
    log_path = tmp_path / "desktop-launcher.log"
    log_path.write_bytes(b"previous launcher output")
    backup_path = tmp_path / "desktop-launcher.log.1"
    backup_path.write_bytes(b"obsolete backup")

    cleared = reset_launcher_log_if_oversized(log_path, max_bytes=8)

    assert cleared is True
    assert log_path.exists() is False
    assert backup_path.exists() is False


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
        "--no-access-log",
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


def test_windows_taskbar_identity_relaunches_the_packaged_vp_launcher(tmp_path: Path) -> None:
    root = _project_root(tmp_path)
    icon = root / "app" / "static" / "assets" / "vintage_programmer.ico"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"ico")
    launcher = root / "VintageProgrammer.exe"
    config = DesktopLaunchConfig(
        project_root=root,
        python_command=("python",),
        browser_path=tmp_path / "chrome.exe",
        browser_profile_dir=root / "browser",
        app_module="app.main:app",
        port=8080,
        startup_timeout_sec=45,
    )

    metadata = windows_taskbar_relaunch_metadata(
        config,
        executable=launcher,
        frozen=True,
    )

    assert metadata == {
        "app_id": WINDOWS_APP_USER_MODEL_ID,
        "relaunch_command": str(launcher.resolve()),
        "display_name": APP_TITLE,
        "icon_resource": f"{icon.resolve()},0",
    }


def test_windows_taskbar_identity_binds_the_chrome_window_to_the_launcher(tmp_path: Path) -> None:
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
    applied: list[tuple[int, dict[str, str]]] = []

    bound = bind_windows_taskbar_identity(
        config,
        platform_name="win32",
        timeout_sec=0,
        window_finder=lambda title: 4242 if title == APP_TITLE else 0,
        property_setter=lambda hwnd, metadata: applied.append((hwnd, dict(metadata))) or True,
        sleeper=lambda _seconds: None,
    )

    assert bound is True
    assert applied[0][0] == 4242
    assert applied[0][1]["app_id"] == WINDOWS_APP_USER_MODEL_ID
    assert applied[0][1]["display_name"] == APP_TITLE


def test_windows_taskbar_window_finder_accepts_unread_badge_title() -> None:
    handle = find_windows_vp_window(
        APP_TITLE,
        platform_name="win32",
        exact_finder=lambda _title: 0,
        candidates_provider=lambda: [
            (101, "Vintage Programmer documentation", "Notepad"),
            (202, "(3) Vintage Programmer", "Chrome_WidgetWin_1"),
        ],
    )

    assert handle == 202


def test_windows_taskbar_identity_retries_slow_window_and_property_store(
    tmp_path: Path,
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
    now = [0.0]
    find_attempts = [0]
    property_attempts = [0]
    diagnostics: dict[str, object] = {}

    def find_window(_title: str) -> int:
        find_attempts[0] += 1
        return 0 if find_attempts[0] < 4 else 4242

    def set_properties(_handle: int, _metadata: object) -> bool:
        property_attempts[0] += 1
        return property_attempts[0] >= 2

    def advance(seconds: float) -> None:
        now[0] += seconds

    bound = bind_windows_taskbar_identity(
        config,
        platform_name="win32",
        timeout_sec=2,
        window_finder=find_window,
        property_setter=set_properties,
        sleeper=advance,
        clock=lambda: now[0],
        diagnostics=diagnostics,
    )

    assert bound is True
    assert find_attempts[0] == 5
    assert property_attempts[0] == 2
    assert diagnostics == {
        "stage": "bound",
        "attempts": 5,
        "property_attempts": 2,
        "window_handle": 4242,
    }


def test_windows_taskbar_identity_reports_window_timeout(tmp_path: Path) -> None:
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
    now = [0.0]
    diagnostics: dict[str, object] = {}

    bound = bind_windows_taskbar_identity(
        config,
        platform_name="win32",
        timeout_sec=0.2,
        window_finder=lambda _title: 0,
        property_setter=lambda _handle, _metadata: True,
        sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds),
        clock=lambda: now[0],
        diagnostics=diagnostics,
    )

    assert bound is False
    assert diagnostics["stage"] == "window_not_found"
    assert diagnostics["property_attempts"] == 0


@pytest.mark.skipif(sys.platform != "win32", reason="requires the Windows Shell")
def test_windows_shell_accepts_taskbar_properties_on_a_real_window() -> None:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.CreateWindowExW.argtypes = [
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = ctypes.c_void_p
    kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    handle = int(
        user32.CreateWindowExW(
            0,
            "STATIC",
            APP_TITLE,
            0x00CF0000,  # WS_OVERLAPPEDWINDOW
            0,
            0,
            320,
            200,
            None,
            None,
            kernel32.GetModuleHandleW(None),
            None,
        )
        or 0
    )
    assert handle
    diagnostics: dict[str, object] = {}
    try:
        assert _set_windows_taskbar_window_properties(
            handle,
            {
                "app_id": WINDOWS_APP_USER_MODEL_ID,
                "relaunch_command": r"C:\VP\VintageProgrammer.exe",
                "display_name": APP_TITLE,
                "icon_resource": r"C:\VP\VintageProgrammer.exe,0",
            },
            diagnostics=diagnostics,
        ), diagnostics
        assert diagnostics["stage"] == "bound"
    finally:
        user32.DestroyWindow(ctypes.c_void_p(handle))


def test_windows_process_app_id_uses_the_same_stable_identity() -> None:
    assigned: list[str] = []

    assert set_windows_process_app_id(
        platform_name="win32",
        setter=lambda app_id: assigned.append(app_id) or 0,
    ) is True
    assert assigned == [WINDOWS_APP_USER_MODEL_ID]
    assert set_windows_process_app_id(platform_name="darwin", setter=lambda _app_id: 0) is False


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
    launcher_log = config.log_path.read_text(encoding="utf-8")
    assert '"event": "cold_launch_started"' in launcher_log
    assert '"event": "preparing_window_started"' in launcher_log
    assert '"event": "backend_process_started"' in launcher_log
    assert '"event": "backend_healthy"' in launcher_log
    assert '"event": "cold_launch_finished"' in launcher_log
    assert '"session_count": 0' in launcher_log


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
