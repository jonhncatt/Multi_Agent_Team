from __future__ import annotations

from pathlib import Path

import pytest

from desktop.launcher import (
    DesktopLaunchConfig,
    LauncherError,
    build_browser_command,
    build_launch_config,
    build_server_command,
    read_dotenv,
    parse_window_size,
    resolve_browser_path,
    resolve_project_root,
    resolve_python_command,
    run_desktop,
)


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

    with pytest.raises(LauncherError, match="cannot share a live Chrome profile"):
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
    assert "--app=http://127.0.0.1:8181" in browser_command
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
