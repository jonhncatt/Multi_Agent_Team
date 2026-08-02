from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Callable, Iterator, Mapping, Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen

from desktop.webview_host import (
    WebViewHostError,
    confirm_stop_and_exit,
    open_webview2_window,
    probe_webview2_host,
)


APP_TITLE = "Vintage Programmer"
DEFAULT_APP_MODULE = "app.main:app"
DEFAULT_APP_PORT = 8080
DEFAULT_STARTUP_TIMEOUT_SEC = 45.0
DEFAULT_INITIAL_WINDOW_SIZE = (1360, 840)
DEFAULT_DESKTOP_UI_SCALE = 0.8
DEFAULT_DESKTOP_SHELL = "auto"
DEFAULT_DESKTOP_CLOSE_TIMEOUT_SEC = 5.0
DESKTOP_INSTANCE_MUTEX = "Local\\VintageProgrammer.Desktop"


class LauncherError(RuntimeError):
    """A user-facing desktop launcher error."""


@dataclass(frozen=True, slots=True)
class DesktopLaunchConfig:
    project_root: Path
    python_command: tuple[str, ...]
    browser_path: Path | None
    browser_profile_dir: Path
    webview_profile_dir: Path
    app_module: str
    port: int
    startup_timeout_sec: float
    shell_mode: str = DEFAULT_DESKTOP_SHELL
    initial_window_width: int = DEFAULT_INITIAL_WINDOW_SIZE[0]
    initial_window_height: int = DEFAULT_INITIAL_WINDOW_SIZE[1]
    ui_scale: float = DEFAULT_DESKTOP_UI_SCALE
    locale: str = "ja-JP"
    close_timeout_sec: float = DEFAULT_DESKTOP_CLOSE_TIMEOUT_SEC

    @property
    def app_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def desktop_url(self) -> str:
        return f"{self.app_url}/?vp_desktop=1&vp_scale={self.ui_scale:g}"

    @property
    def health_url(self) -> str:
        return f"{self.app_url}/api/health"

    @property
    def lifecycle_url(self) -> str:
        return f"{self.app_url}/api/desktop/lifecycle"

    @property
    def log_path(self) -> Path:
        return self.project_root / "app" / "data" / "runtime" / "desktop-launcher.log"

    @property
    def window_initialized_marker(self) -> Path:
        return self.browser_profile_dir / ".vp-window-initialized"

    def diagnostics(self) -> dict[str, object]:
        payload = asdict(self)
        payload["project_root"] = str(self.project_root)
        payload["python_command"] = list(self.python_command)
        payload["browser_path"] = str(self.browser_path) if self.browser_path else ""
        payload["browser_profile_dir"] = str(self.browser_profile_dir)
        payload["webview_profile_dir"] = str(self.webview_profile_dir)
        payload["app_url"] = self.app_url
        payload["desktop_url"] = self.desktop_url
        payload["health_url"] = self.health_url
        payload["log_path"] = str(self.log_path)
        return payload


def _looks_like_project_root(path: Path) -> bool:
    return (path / "app" / "main.py").is_file() and (path / "requirements.txt").is_file()


def _walk_candidates(start: Path) -> Iterator[Path]:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    yield current
    yield from current.parents


def resolve_project_root(
    explicit_root: str | Path | None = None,
    *,
    cwd: Path | None = None,
    executable: Path | None = None,
    module_file: Path | None = None,
) -> Path:
    if explicit_root:
        resolved = Path(explicit_root).expanduser().resolve()
        if not _looks_like_project_root(resolved):
            raise LauncherError(
                f"The configured project root is not a Vintage Programmer checkout: {resolved}"
            )
        return resolved

    starts = [cwd or Path.cwd()]
    if executable is not None:
        starts.append(executable)
    elif getattr(sys, "frozen", False):
        starts.append(Path(sys.executable))
    starts.append(module_file or Path(__file__))

    seen: set[Path] = set()
    for start in starts:
        for candidate in _walk_candidates(start):
            if candidate in seen:
                continue
            seen.add(candidate)
            if _looks_like_project_root(candidate):
                return candidate
    raise LauncherError(
        "Vintage Programmer project files were not found. Put VintageProgrammer.exe in the "
        "repository root, or set VP_DESKTOP_PROJECT_ROOT to that directory."
    )


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def _dotenv_path(project_root: Path, env: Mapping[str, str]) -> Path:
    configured = str(env.get("VP_DOTENV_PATH") or "").strip()
    if not configured:
        return project_root / ".env"
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve()


def _setting(key: str, *, env: Mapping[str, str], dotenv: Mapping[str, str], default: str = "") -> str:
    # app.config intentionally lets repository .env values override VP_* process values.
    # Matching that behavior keeps the launcher's port and the server's port identical.
    if key.startswith("VP_") and key in dotenv:
        return str(dotenv[key]).strip()
    return str(env.get(key, default) or default).strip()


def _resolve_relative_path(raw: str, project_root: Path) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve()


def parse_window_size(raw: str) -> tuple[int, int]:
    normalized = str(raw or "").strip().lower().replace("x", ",")
    parts = [item.strip() for item in normalized.split(",")]
    if len(parts) != 2:
        raise LauncherError(
            f"VP_DESKTOP_INITIAL_WINDOW_SIZE must look like 1360,840, got: {raw}"
        )
    try:
        width, height = (int(item) for item in parts)
    except ValueError as exc:
        raise LauncherError(
            f"VP_DESKTOP_INITIAL_WINDOW_SIZE must contain two integers, got: {raw}"
        ) from exc
    if width < 900 or height < 600 or width > 7680 or height > 4320:
        raise LauncherError(
            "VP_DESKTOP_INITIAL_WINDOW_SIZE must be between 900x600 and 7680x4320."
        )
    return width, height


def parse_ui_scale(raw: str) -> float:
    try:
        scale = float(str(raw or "").strip())
    except ValueError as exc:
        raise LauncherError(f"VP_DESKTOP_UI_SCALE must be numeric, got: {raw}") from exc
    if scale < 0.65 or scale > 1.25:
        raise LauncherError("VP_DESKTOP_UI_SCALE must be between 0.65 and 1.25.")
    return scale


def parse_shell_mode(raw: str) -> str:
    mode = str(raw or DEFAULT_DESKTOP_SHELL).strip().lower()
    if mode not in {"auto", "webview2", "chrome"}:
        raise LauncherError("VP_DESKTOP_SHELL must be auto, webview2, or chrome.")
    return mode


def resolve_python_command(
    project_root: Path,
    *,
    frozen: bool | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[str, ...]:
    candidates = (
        project_root / ".venv" / "Scripts" / "python.exe",
        project_root / ".venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return (str(candidate.resolve()),)

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not is_frozen and Path(sys.executable).is_file():
        return (str(Path(sys.executable).resolve()),)
    for command in ("python.exe", "python", "py.exe", "py", "python3"):
        resolved = which(command)
        if resolved:
            return (str(Path(resolved).resolve()),)
    raise LauncherError(
        "Python was not found. Create .venv in the Vintage Programmer repository before using the desktop launcher."
    )


def _browser_candidates(platform_name: str, env: Mapping[str, str]) -> list[Path]:
    if platform_name == "darwin":
        return [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ]
    if platform_name == "win32":
        roots = [
            env.get("PROGRAMFILES", ""),
            env.get("PROGRAMFILES(X86)", ""),
            env.get("LOCALAPPDATA", ""),
        ]
        candidates: list[Path] = []
        for raw_root in roots:
            if not raw_root:
                continue
            root = Path(raw_root)
            candidates.append(root / "Google" / "Chrome" / "Application" / "chrome.exe")
        for raw_root in roots:
            if not raw_root:
                continue
            root = Path(raw_root)
            candidates.append(root / "Microsoft" / "Edge" / "Application" / "msedge.exe")
        return candidates
    return []


def resolve_browser_path(
    *,
    configured_path: str = "",
    platform_name: str | None = None,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> Path:
    current_env = os.environ if env is None else env
    raw_configured = str(configured_path or "").strip()
    if raw_configured:
        configured = Path(raw_configured).expanduser()
        if configured.is_file():
            return configured.resolve()
        resolved_command = which(raw_configured)
        if resolved_command:
            return Path(resolved_command).resolve()
        raise LauncherError(f"The configured desktop browser does not exist: {raw_configured}")

    current_platform = platform_name or sys.platform
    for candidate in _browser_candidates(current_platform, current_env):
        if candidate.is_file():
            return candidate.resolve()
    for command in ("chrome.exe", "chrome", "google-chrome", "msedge.exe", "msedge", "microsoft-edge"):
        resolved_command = which(command)
        if resolved_command:
            return Path(resolved_command).resolve()
    raise LauncherError(
        "Google Chrome or Microsoft Edge was not found. Install Chrome, or set VP_DESKTOP_BROWSER_PATH."
    )


def build_launch_config(
    *,
    project_root: str | Path | None = None,
    browser_path: str = "",
    env: Mapping[str, str] | None = None,
) -> DesktopLaunchConfig:
    current_env = dict(os.environ if env is None else env)
    root = resolve_project_root(project_root or current_env.get("VP_DESKTOP_PROJECT_ROOT"))
    dotenv = read_dotenv(_dotenv_path(root, current_env))

    raw_port = _setting("VP_APP_PORT", env=current_env, dotenv=dotenv, default=str(DEFAULT_APP_PORT))
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise LauncherError(f"VP_APP_PORT must be an integer, got: {raw_port}") from exc
    if port < 1 or port > 65535:
        raise LauncherError(f"VP_APP_PORT must be between 1 and 65535, got: {port}")

    raw_timeout = _setting(
        "VP_DESKTOP_STARTUP_TIMEOUT_SEC",
        env=current_env,
        dotenv=dotenv,
        default=str(DEFAULT_STARTUP_TIMEOUT_SEC),
    )
    try:
        startup_timeout_sec = max(1.0, float(raw_timeout))
    except ValueError as exc:
        raise LauncherError(f"VP_DESKTOP_STARTUP_TIMEOUT_SEC must be numeric, got: {raw_timeout}") from exc

    raw_close_timeout = _setting(
        "VP_DESKTOP_CLOSE_TIMEOUT_SEC",
        env=current_env,
        dotenv=dotenv,
        default=str(DEFAULT_DESKTOP_CLOSE_TIMEOUT_SEC),
    )
    try:
        close_timeout_sec = max(1.0, min(60.0, float(raw_close_timeout)))
    except ValueError as exc:
        raise LauncherError(
            f"VP_DESKTOP_CLOSE_TIMEOUT_SEC must be numeric, got: {raw_close_timeout}"
        ) from exc

    desktop_profile_raw = _setting(
        "VP_DESKTOP_BROWSER_USER_DATA_DIR",
        env=current_env,
        dotenv=dotenv,
        default="app/data/desktop_browser_profile",
    )
    desktop_profile = _resolve_relative_path(desktop_profile_raw, root)
    webview_profile = _resolve_relative_path(
        _setting(
            "VP_DESKTOP_WEBVIEW2_USER_DATA_DIR",
            env=current_env,
            dotenv=dotenv,
            default="app/data/desktop_webview2_profile",
        ),
        root,
    )
    if desktop_profile == webview_profile:
        raise LauncherError(
            "VP_DESKTOP_BROWSER_USER_DATA_DIR and VP_DESKTOP_WEBVIEW2_USER_DATA_DIR "
            "must use different directories."
        )
    agent_profile_raw = _setting("VP_BROWSER_USER_DATA_DIR", env=current_env, dotenv=dotenv)
    if agent_profile_raw:
        agent_profile = _resolve_relative_path(agent_profile_raw, root)
        if agent_profile in {desktop_profile, webview_profile}:
            raise LauncherError(
                "Desktop shell profiles must differ from VP_BROWSER_USER_DATA_DIR; "
                "the desktop window and Agent browser cannot share a live browser profile."
            )

    shell_mode = parse_shell_mode(
        _setting(
            "VP_DESKTOP_SHELL",
            env=current_env,
            dotenv=dotenv,
            default=DEFAULT_DESKTOP_SHELL,
        )
    )

    configured_browser = browser_path or _setting(
        "VP_DESKTOP_BROWSER_PATH", env=current_env, dotenv=dotenv
    )
    initial_window_width, initial_window_height = parse_window_size(
        _setting(
            "VP_DESKTOP_INITIAL_WINDOW_SIZE",
            env=current_env,
            dotenv=dotenv,
            default=f"{DEFAULT_INITIAL_WINDOW_SIZE[0]},{DEFAULT_INITIAL_WINDOW_SIZE[1]}",
        )
    )
    ui_scale = parse_ui_scale(
        _setting(
            "VP_DESKTOP_UI_SCALE",
            env=current_env,
            dotenv=dotenv,
            default=str(DEFAULT_DESKTOP_UI_SCALE),
        )
    )
    resolved_browser: Path | None
    try:
        resolved_browser = resolve_browser_path(
            configured_path=configured_browser,
            env=current_env,
        )
    except LauncherError:
        browser_is_required = shell_mode == "chrome" or sys.platform != "win32"
        if configured_browser or browser_is_required:
            raise
        resolved_browser = None

    return DesktopLaunchConfig(
        project_root=root,
        python_command=resolve_python_command(root),
        browser_path=resolved_browser,
        browser_profile_dir=desktop_profile,
        webview_profile_dir=webview_profile,
        app_module=_setting(
            "VP_APP_MODULE", env=current_env, dotenv=dotenv, default=DEFAULT_APP_MODULE
        ),
        port=port,
        startup_timeout_sec=startup_timeout_sec,
        shell_mode=shell_mode,
        initial_window_width=initial_window_width,
        initial_window_height=initial_window_height,
        ui_scale=ui_scale,
        locale=_setting(
            "VP_DEFAULT_LOCALE",
            env=current_env,
            dotenv=dotenv,
            default="ja-JP",
        ),
        close_timeout_sec=close_timeout_sec,
    )


def build_server_command(config: DesktopLaunchConfig) -> list[str]:
    return [
        *config.python_command,
        "-m",
        "uvicorn",
        config.app_module,
        "--host",
        "127.0.0.1",
        "--port",
        str(config.port),
    ]


def build_browser_command(
    config: DesktopLaunchConfig, *, initialize_window: bool = False
) -> list[str]:
    if config.browser_path is None:
        raise LauncherError(
            "Chrome fallback is unavailable. Install Chrome or set VP_DESKTOP_BROWSER_PATH."
        )
    command = [
        str(config.browser_path),
        f"--app={config.desktop_url}",
        f"--user-data-dir={config.browser_profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
    ]
    if initialize_window:
        command.extend(
            [
                "--start-maximized",
                f"--window-size={config.initial_window_width},{config.initial_window_height}",
            ]
        )
    return command


def request_local_json(
    url: str,
    *,
    method: str = "GET",
    timeout_sec: float = 2.0,
) -> dict[str, object]:
    normalized_method = str(method or "GET").strip().upper()
    request = Request(
        url,
        data=b"" if normalized_method == "POST" else None,
        method=normalized_method,
        headers={"Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout_sec) as response:  # noqa: S310 - localhost URL is constructed internally
            status = int(getattr(response, "status", 200) or 200)
            if status < 200 or status >= 300:
                raise LauncherError(f"Local runtime request failed with HTTP {status}.")
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise LauncherError(f"Local runtime request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise LauncherError("Local runtime returned an invalid response.")
    return dict(payload)


def read_health_payload(url: str, *, timeout_sec: float = 1.0) -> dict[str, object]:
    try:
        payload = request_local_json(url, timeout_sec=timeout_sec)
    except LauncherError:
        return {}
    if payload.get("ok") is not True or not payload.get("app_version"):
        return {}
    return payload


def health_check(url: str, *, timeout_sec: float = 1.0) -> bool:
    if not read_health_payload(url, timeout_sec=timeout_sec):
        return False
    return True


def wait_until_healthy(
    url: str,
    *,
    timeout_sec: float,
    process: subprocess.Popen[bytes] | None = None,
    probe: Callable[[str], bool] = health_check,
) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if probe(url):
            return True
        if process is not None and process.poll() is not None:
            return False
        time.sleep(0.25)
    return False


def _server_creation_kwargs() -> dict[str, object]:
    if os.name == "nt":
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        return {"creationflags": flags}
    return {"start_new_session": True}


def _browser_creation_kwargs() -> dict[str, object]:
    if os.name == "nt":
        flags = int(getattr(subprocess, "DETACHED_PROCESS", 0)) | int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        return {"creationflags": flags}
    # A Chrome App Mode window must outlive the short launcher process and the
    # terminal that invoked it during macOS/Linux development previews.
    return {"start_new_session": True}


def start_server(config: DesktopLaunchConfig) -> tuple[subprocess.Popen[bytes], object]:
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = config.log_path.open("ab", buffering=0)
    process = subprocess.Popen(
        build_server_command(config),
        cwd=str(config.project_root),
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        close_fds=True,
        **_server_creation_kwargs(),
    )
    return process, log_handle


def start_browser(config: DesktopLaunchConfig) -> subprocess.Popen[bytes]:
    config.browser_profile_dir.mkdir(parents=True, exist_ok=True)
    initialize_window = not config.window_initialized_marker.is_file()
    process = subprocess.Popen(
        build_browser_command(config, initialize_window=initialize_window),
        cwd=str(config.project_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **_browser_creation_kwargs(),
    )
    if initialize_window:
        config.window_initialized_marker.write_text("1\n", encoding="utf-8")
    return process


def should_try_webview2(
    config: DesktopLaunchConfig,
    *,
    platform_name: str | None = None,
) -> bool:
    return (platform_name or sys.platform) == "win32" and config.shell_mode in {
        "auto",
        "webview2",
    }


def read_desktop_lifecycle(config: DesktopLaunchConfig) -> dict[str, object]:
    payload = request_local_json(config.lifecycle_url, timeout_sec=2.0)
    if payload.get("ok") is not True:
        raise LauncherError("Local runtime lifecycle status is unavailable.")
    return payload


def _active_lifecycle_items(payload: Mapping[str, object]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    active_runs = [dict(item) for item in list(payload.get("active_runs") or []) if isinstance(item, dict)]
    active_evals = [dict(item) for item in list(payload.get("active_evals") or []) if isinstance(item, dict)]
    return active_runs, active_evals


def cancel_active_chat_runs(
    config: DesktopLaunchConfig,
    active_runs: Sequence[Mapping[str, object]],
) -> None:
    for item in active_runs:
        run_id = str(item.get("run_id") or "").strip()
        if not run_id:
            continue
        try:
            request_local_json(
                f"{config.app_url}/api/chat/runs/{run_id}/cancel",
                method="POST",
                timeout_sec=2.0,
            )
        except LauncherError as exc:
            _append_launcher_note(config, f"Could not request cancellation for run {run_id}: {exc}")


def wait_for_chat_runs_to_stop(config: DesktopLaunchConfig) -> bool:
    deadline = time.monotonic() + config.close_timeout_sec
    while time.monotonic() < deadline:
        try:
            active_runs, _active_evals = _active_lifecycle_items(read_desktop_lifecycle(config))
        except LauncherError:
            return False
        if not active_runs:
            return True
        time.sleep(0.15)
    return False


def handle_desktop_close(
    config: DesktopLaunchConfig,
    owner_window: object,
    *,
    confirmer: Callable[..., bool] = confirm_stop_and_exit,
) -> bool:
    try:
        lifecycle = read_desktop_lifecycle(config)
        active_runs, active_evals = _active_lifecycle_items(lifecycle)
        active_count = len(active_runs) + len(active_evals)
    except LauncherError as exc:
        # An older or temporarily unavailable backend cannot prove that closing
        # is safe. Ask for the destructive choice instead of silently exiting.
        _append_launcher_note(config, f"Could not read close lifecycle status: {exc}")
        active_runs = []
        active_count = 1

    if active_count == 0:
        return True
    if not confirmer(owner_window, active_count=active_count, locale=config.locale):
        return False

    cancel_active_chat_runs(config, active_runs)
    if active_runs and not wait_for_chat_runs_to_stop(config):
        _append_launcher_note(
            config,
            "Active Agent cleanup did not finish before the desktop close grace period; "
            "the managed backend will now be terminated.",
        )
    return True


def start_webview2(config: DesktopLaunchConfig) -> None:
    open_webview2_window(
        url=config.desktop_url,
        project_root=config.project_root,
        profile_dir=config.webview_profile_dir,
        width=config.initial_window_width,
        height=config.initial_window_height,
        closing_handler=lambda owner_window: handle_desktop_close(config, owner_window),
    )


def _append_launcher_note(config: DesktopLaunchConfig, message: str) -> None:
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    with config.log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[desktop-shell] {message.strip()}\n")


def stop_owned_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def terminate_managed_server_pid(pid: int, *, platform_name: str | None = None) -> bool:
    server_pid = int(pid or 0)
    if server_pid <= 0 or server_pid == os.getpid() or (platform_name or sys.platform) != "win32":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    open_process.restype = ctypes.c_void_p
    terminate_process = kernel32.TerminateProcess
    terminate_process.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    terminate_process.restype = ctypes.c_int
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    wait_for_single_object.restype = ctypes.c_uint32
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    process_handle = open_process(0x0001 | 0x00100000, False, server_pid)  # TERMINATE | SYNCHRONIZE
    if not process_handle:
        return False
    try:
        if not terminate_process(process_handle, 0):
            return False
        wait_for_single_object(process_handle, 8000)
        return True
    finally:
        close_handle(process_handle)


def focus_existing_desktop_window(
    *,
    platform_name: str | None = None,
    user32: object | None = None,
) -> bool:
    if (platform_name or sys.platform) != "win32":
        return False
    api = user32 or ctypes.windll.user32
    window_handle = int(api.FindWindowW(None, APP_TITLE) or 0)
    if not window_handle:
        return False
    api.ShowWindow(window_handle, 9)  # SW_RESTORE
    api.SetForegroundWindow(window_handle)
    return True


@contextmanager
def desktop_instance_guard(
    *,
    platform_name: str | None = None,
    create_mutex: Callable[..., object] | None = None,
    get_last_error: Callable[[], int] | None = None,
    close_handle: Callable[[object], object] | None = None,
    focus_existing: Callable[[], bool] = focus_existing_desktop_window,
) -> Iterator[bool]:
    if (platform_name or sys.platform) != "win32":
        yield True
        return

    if create_mutex is None or get_last_error is None or close_handle is None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        native_create_mutex = kernel32.CreateMutexW
        native_create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        native_create_mutex.restype = ctypes.c_void_p
        native_close_handle = kernel32.CloseHandle
        native_close_handle.argtypes = [ctypes.c_void_p]
        native_close_handle.restype = ctypes.c_int
        create_mutex = native_create_mutex
        get_last_error = ctypes.get_last_error
        close_handle = native_close_handle

    handle = create_mutex(None, False, DESKTOP_INSTANCE_MUTEX)
    if not handle:
        raise LauncherError("Windows could not create the desktop single-instance guard.")
    already_running = int(get_last_error() or 0) == 183  # ERROR_ALREADY_EXISTS
    try:
        if already_running:
            focus_existing()
        yield not already_running
    finally:
        close_handle(handle)


@contextmanager
def startup_lock(path: Path, *, timeout_sec: float = 15.0) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    deadline = time.monotonic() + timeout_sec
    locked = False
    try:
        while time.monotonic() < deadline:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except (BlockingIOError, OSError):
                time.sleep(0.1)
        if not locked:
            raise LauncherError("Another Vintage Programmer desktop launch is still starting.")
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def run_desktop(config: DesktopLaunchConfig) -> None:
    owned_server: subprocess.Popen[bytes] | None = None
    log_handle: object | None = None
    adopted_server_pid = 0
    native_window_closed = False
    server_stopped = False
    lock_path = config.project_root / "app" / "data" / "runtime" / "desktop-launcher.lock"
    try:
        with startup_lock(lock_path):
            if not health_check(config.health_url):
                owned_server, log_handle = start_server(config)
                if not wait_until_healthy(
                    config.health_url,
                    timeout_sec=config.startup_timeout_sec,
                    process=owned_server,
                ):
                    raise LauncherError(
                        f"Vintage Programmer did not start. See the launcher log: {config.log_path}"
                    )
            else:
                health_payload = read_health_payload(config.health_url)
                try:
                    adopted_server_pid = max(0, int(health_payload.get("process_id") or 0))
                except (TypeError, ValueError):
                    adopted_server_pid = 0
        # WebView2 owns the foreground GUI loop until the user closes the
        # native window. Keep that lifetime outside the short startup lock so a
        # window does not make later health checks look like a stuck launch.
        if should_try_webview2(config):
            try:
                start_webview2(config)
                native_window_closed = True
            except WebViewHostError as exc:
                if config.shell_mode == "webview2":
                    raise LauncherError(str(exc)) from exc
                _append_launcher_note(
                    config,
                    f"Native WebView2 unavailable; using Chrome App Mode. {exc}",
                )
                if config.browser_path is None:
                    raise LauncherError(
                        f"{exc} Chrome fallback is also unavailable; install Chrome or Edge."
                    ) from exc
                start_browser(config)
        else:
            if config.shell_mode == "webview2":
                raise LauncherError("VP_DESKTOP_SHELL=webview2 is supported only on Windows.")
            start_browser(config)
    except BaseException:
        if owned_server is not None:
            stop_owned_server(owned_server)
            server_stopped = True
        raise
    finally:
        if native_window_closed and not server_stopped:
            if owned_server is not None:
                stop_owned_server(owned_server)
                server_stopped = True
            elif adopted_server_pid:
                if not terminate_managed_server_pid(adopted_server_pid):
                    _append_launcher_note(
                        config,
                        f"Could not stop the reused backend process {adopted_server_pid}.",
                    )
        if log_handle is not None:
            close = getattr(log_handle, "close", None)
            if callable(close):
                close()


def _show_error(message: str) -> None:
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, f"{APP_TITLE} - Startup Error", 0x10)
        return
    if sys.stderr is not None:
        print(f"{APP_TITLE}: {message}", file=sys.stderr)


def _write_diagnostics(payload: dict[str, object], output_path: str) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if output_path:
        Path(output_path).expanduser().resolve().write_text(serialized + "\n", encoding="utf-8")
    elif sys.stdout is not None:
        print(serialized)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open Vintage Programmer in a native Windows WebView2 window or Chrome fallback."
    )
    parser.add_argument("--project-root", default="", help="Vintage Programmer repository root")
    parser.add_argument("--browser-path", default="", help="Chrome or Edge executable path")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print configuration without launching")
    parser.add_argument(
        "--probe-native-shell",
        action="store_true",
        help="Validate the bundled Windows WebView2 host without opening a window",
    )
    parser.add_argument("--diagnostics-file", default="", help="Write dry-run diagnostics to a JSON file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = build_launch_config(
            project_root=args.project_root or None,
            browser_path=args.browser_path,
        )
        if args.dry_run:
            diagnostics = config.diagnostics()
            if args.probe_native_shell:
                diagnostics["native_shell_probe"] = probe_webview2_host()
            _write_diagnostics(diagnostics, args.diagnostics_file)
            return 0
        with desktop_instance_guard() as is_primary_instance:
            if not is_primary_instance:
                return 0
            run_desktop(config)
        return 0
    except (LauncherError, OSError, subprocess.SubprocessError) as exc:
        _show_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
