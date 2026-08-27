from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from dataclasses import asdict, dataclass, replace
from html import escape
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable, Iterator, Mapping, Sequence
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID

APP_TITLE = "Vintage Programmer"
WINDOWS_APP_USER_MODEL_ID = "VintageProgrammer.Desktop"
DEFAULT_APP_MODULE = "app.main:app"
DEFAULT_APP_PORT = 8080
DEFAULT_STARTUP_TIMEOUT_SEC = 45.0
DEFAULT_INITIAL_WINDOW_SIZE = (1360, 840)
DEFAULT_DESKTOP_UI_SCALE = 0.8
DEFAULT_LAUNCHER_LOG_MAX_BYTES = 2 * 1024 * 1024
DESKTOP_INSTANCE_MUTEX = "Local\\VintageProgrammer.Desktop"
DESKTOP_CONTROL_TOKEN_FILENAME = "desktop-control-token"
DESKTOP_PREPARING_FILENAME = "desktop-preparing.html"
DESKTOP_PREPARING_STATE_FILENAME = "desktop-preparing-state.js"
PROJECT_ROOT_MARKERS = (
    Path("app/main.py"),
    Path("requirements.txt"),
    Path("desktop/launcher.py"),
)

_PKEY_APP_USER_MODEL_RELAUNCH_COMMAND_PID = 2
_PKEY_APP_USER_MODEL_RELAUNCH_ICON_RESOURCE_PID = 3
_PKEY_APP_USER_MODEL_RELAUNCH_DISPLAY_NAME_PID = 4
_PKEY_APP_USER_MODEL_ID_PID = 5
_APP_USER_MODEL_PROPERTY_SET = "9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3"
_IID_IPROPERTY_STORE = "886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"


class _GUID(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_ubyte * 8),
    ]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [
        ("fmtid", _GUID),
        ("pid", ctypes.c_uint32),
    ]


class LauncherError(RuntimeError):
    """A user-facing desktop launcher error."""


@dataclass(frozen=True, slots=True)
class DesktopLaunchConfig:
    project_root: Path
    python_command: tuple[str, ...]
    browser_path: Path | None
    browser_profile_dir: Path
    app_module: str
    port: int
    startup_timeout_sec: float
    initial_window_width: int = DEFAULT_INITIAL_WINDOW_SIZE[0]
    initial_window_height: int = DEFAULT_INITIAL_WINDOW_SIZE[1]
    ui_scale: float = DEFAULT_DESKTOP_UI_SCALE
    desktop_control_token: str = ""

    @property
    def app_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def desktop_url(self) -> str:
        return f"{self.app_url}/?vp_desktop=1&vp_scale={self.ui_scale:g}"

    @property
    def chrome_desktop_url(self) -> str:
        base = f"{self.desktop_url}&vp_host=chrome"
        token = str(self.desktop_control_token or "").strip()
        return f"{base}#vp_control={quote(token, safe='')}" if token else base

    @property
    def health_url(self) -> str:
        return f"{self.app_url}/api/health"

    @property
    def log_path(self) -> Path:
        return self.project_root / "app" / "data" / "runtime" / "desktop-launcher.log"

    @property
    def desktop_control_token_path(self) -> Path:
        return self.project_root / "app" / "data" / "runtime" / DESKTOP_CONTROL_TOKEN_FILENAME

    @property
    def desktop_preparing_path(self) -> Path:
        return self.project_root / "app" / "data" / "runtime" / DESKTOP_PREPARING_FILENAME

    @property
    def desktop_preparing_state_path(self) -> Path:
        return self.project_root / "app" / "data" / "runtime" / DESKTOP_PREPARING_STATE_FILENAME

    @property
    def window_initialized_marker(self) -> Path:
        return self.browser_profile_dir / ".vp-window-initialized"

    def diagnostics(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("desktop_control_token", None)
        payload["project_root"] = str(self.project_root)
        payload["python_command"] = list(self.python_command)
        payload["browser_path"] = str(self.browser_path) if self.browser_path else ""
        payload["browser_profile_dir"] = str(self.browser_profile_dir)
        payload["app_url"] = self.app_url
        payload["desktop_url"] = self.desktop_url
        payload["chrome_desktop_url"] = self.chrome_desktop_url.split("#", 1)[0]
        payload["health_url"] = self.health_url
        payload["log_path"] = str(self.log_path)
        return payload


def _looks_like_project_root(path: Path) -> bool:
    return all((path / marker).is_file() for marker in PROJECT_ROOT_MARKERS)


def resolve_project_root(
    explicit_root: str | Path | None = None,
    *,
    cwd: Path | None = None,
    executable: Path | None = None,
) -> Path:
    if explicit_root:
        resolved = Path(explicit_root).expanduser().resolve()
        if not _looks_like_project_root(resolved):
            raise LauncherError(
                f"The configured project root is not a Vintage Programmer checkout: {resolved}"
            )
        return resolved

    if executable is not None:
        candidate = Path(executable).expanduser().resolve()
        if candidate.is_file() or candidate.suffix.lower() == ".exe":
            candidate = candidate.parent
    elif getattr(sys, "frozen", False):
        candidate = Path(sys.executable).resolve().parent
    else:
        candidate = (cwd or Path.cwd()).expanduser().resolve()

    if _looks_like_project_root(candidate):
        return candidate
    expected = ", ".join(str(marker).replace("\\", "/") for marker in PROJECT_ROOT_MARKERS)
    raise LauncherError(
        f"VintageProgrammer.exe must be in the Vintage Programmer repository root: {candidate}. "
        f"Expected files: {expected}. To bind another explicit location, set VP_DESKTOP_PROJECT_ROOT."
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


def validate_chrome_shell_mode(raw: str) -> None:
    mode = str(raw or "auto").strip().lower()
    if mode not in {"auto", "chrome"}:
        raise LauncherError(
            "Vintage Programmer desktop now supports Chrome App Mode only. "
            "Remove VP_DESKTOP_SHELL or set it to chrome."
        )


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
    for command in ("chrome.exe", "chrome", "google-chrome"):
        resolved_command = which(command)
        if resolved_command:
            return Path(resolved_command).resolve()
    raise LauncherError(
        "Google Chrome was not found. Install Chrome, or set VP_DESKTOP_BROWSER_PATH."
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

    desktop_profile_raw = _setting(
        "VP_DESKTOP_BROWSER_USER_DATA_DIR",
        env=current_env,
        dotenv=dotenv,
        default="app/data/desktop_browser_profile",
    )
    desktop_profile = _resolve_relative_path(desktop_profile_raw, root)
    agent_profile_raw = _setting("VP_BROWSER_USER_DATA_DIR", env=current_env, dotenv=dotenv)
    if agent_profile_raw:
        agent_profile = _resolve_relative_path(agent_profile_raw, root)
        if agent_profile == desktop_profile:
            raise LauncherError(
                "The desktop Chrome profile must differ from VP_BROWSER_USER_DATA_DIR; "
                "the desktop window and Agent browser cannot share a live browser profile."
            )

    validate_chrome_shell_mode(
        _setting(
            "VP_DESKTOP_SHELL",
            env=current_env,
            dotenv=dotenv,
            default="auto",
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
    resolved_browser = resolve_browser_path(
        configured_path=configured_browser,
        env=current_env,
    )

    return DesktopLaunchConfig(
        project_root=root,
        python_command=resolve_python_command(root),
        browser_path=resolved_browser,
        browser_profile_dir=desktop_profile,
        app_module=_setting(
            "VP_APP_MODULE", env=current_env, dotenv=dotenv, default=DEFAULT_APP_MODULE
        ),
        port=port,
        startup_timeout_sec=startup_timeout_sec,
        initial_window_width=initial_window_width,
        initial_window_height=initial_window_height,
        ui_scale=ui_scale,
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
        "--no-access-log",
    ]


def build_browser_command(
    config: DesktopLaunchConfig,
    *,
    initialize_window: bool = False,
    app_url: str = "",
) -> list[str]:
    if config.browser_path is None:
        raise LauncherError(
            "Google Chrome is unavailable. Install Chrome or set VP_DESKTOP_BROWSER_PATH."
        )
    command = [
        str(config.browser_path),
        f"--app={str(app_url or config.chrome_desktop_url).strip()}",
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


def wait_until_stopped(
    url: str,
    *,
    timeout_sec: float,
    probe: Callable[[str], bool] = health_check,
) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if not probe(url):
            return True
        time.sleep(0.1)
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


def windows_taskbar_relaunch_metadata(
    config: DesktopLaunchConfig,
    *,
    executable: str | Path | None = None,
    frozen: bool | None = None,
) -> dict[str, str]:
    """Return the stable Windows taskbar identity and launcher-owned relaunch data."""

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    if is_frozen:
        launcher_path = Path(executable or sys.executable).expanduser().resolve()
        relaunch_parts = [str(launcher_path)]
    else:
        relaunch_parts = [
            *config.python_command,
            "-m",
            "desktop.launcher",
            "--project-root",
            str(config.project_root),
        ]
    web_icon_path = (
        config.project_root / "app" / "static" / "assets" / "vintage_programmer.ico"
    ).resolve()
    build_icon_path = (
        config.project_root
        / "desktop"
        / "windows"
        / "assets"
        / "vintage_programmer.ico"
    ).resolve()
    icon_path = web_icon_path if web_icon_path.is_file() else build_icon_path
    if not icon_path.is_file() and is_frozen:
        icon_path = launcher_path
    return {
        "app_id": WINDOWS_APP_USER_MODEL_ID,
        "relaunch_command": subprocess.list2cmdline([str(item) for item in relaunch_parts]),
        "display_name": APP_TITLE,
        "icon_resource": f"{icon_path},0",
    }


def set_windows_process_app_id(
    *,
    platform_name: str | None = None,
    setter: Callable[[str], int] | None = None,
) -> bool:
    """Give the short launcher process the same explicit identity as the VP window."""

    if (platform_name or sys.platform) != "win32":
        return False
    try:
        if setter is None:
            native_setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
            native_setter.argtypes = [ctypes.c_wchar_p]
            native_setter.restype = ctypes.c_int32
            setter = native_setter
        return int(setter(WINDOWS_APP_USER_MODEL_ID)) >= 0
    except Exception:
        return False


def _guid_from_text(value: str) -> _GUID:
    return _GUID.from_buffer_copy(UUID(str(value)).bytes_le)


def _set_windows_taskbar_window_properties(
    window_handle: int,
    metadata: Mapping[str, str],
) -> bool:
    """Set relaunch metadata and AppUserModelID on a Chrome-owned VP HWND."""

    if sys.platform != "win32" or not int(window_handle or 0):
        return False

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    propsys = ctypes.WinDLL("propsys", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    iid_property_store = _guid_from_text(_IID_IPROPERTY_STORE)
    property_set_guid = _guid_from_text(_APP_USER_MODEL_PROPERTY_SET)
    property_store = ctypes.c_void_p()
    variant_size = 24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16

    shell32.SHGetPropertyStoreForWindow.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_int32
    propsys.InitPropVariantFromString.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
    propsys.InitPropVariantFromString.restype = ctypes.c_int32
    ole32.PropVariantClear.argtypes = [ctypes.c_void_p]
    ole32.PropVariantClear.restype = ctypes.c_int32
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole32.CoInitializeEx.restype = ctypes.c_int32
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None

    coinit_result = int(ole32.CoInitializeEx(None, 0x2))  # COINIT_APARTMENTTHREADED
    should_uninitialize = coinit_result in {0, 1}
    if coinit_result < 0 and coinit_result != -2147417850:  # RPC_E_CHANGED_MODE
        return False
    try:
        result = int(
            shell32.SHGetPropertyStoreForWindow(
                ctypes.c_void_p(int(window_handle)),
                ctypes.byref(iid_property_store),
                ctypes.byref(property_store),
            )
        )
        if result < 0 or not property_store.value:
            return False

        vtable = ctypes.cast(
            property_store,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
        ).contents
        set_value = ctypes.WINFUNCTYPE(
            ctypes.c_int32,
            ctypes.c_void_p,
            ctypes.POINTER(_PROPERTYKEY),
            ctypes.c_void_p,
        )(vtable[6])
        release = ctypes.WINFUNCTYPE(ctypes.c_uint32, ctypes.c_void_p)(vtable[2])
        values = (
            (_PKEY_APP_USER_MODEL_RELAUNCH_COMMAND_PID, metadata.get("relaunch_command", "")),
            (_PKEY_APP_USER_MODEL_RELAUNCH_DISPLAY_NAME_PID, metadata.get("display_name", "")),
            (_PKEY_APP_USER_MODEL_RELAUNCH_ICON_RESOURCE_PID, metadata.get("icon_resource", "")),
            (_PKEY_APP_USER_MODEL_ID_PID, metadata.get("app_id", "")),
        )
        try:
            for property_id, raw_value in values:
                value = str(raw_value or "").strip()
                if not value:
                    return False
                variant = ctypes.create_string_buffer(variant_size)
                if int(propsys.InitPropVariantFromString(value, ctypes.byref(variant))) < 0:
                    return False
                try:
                    key = _PROPERTYKEY(property_set_guid, property_id)
                    if int(set_value(property_store, ctypes.byref(key), ctypes.byref(variant))) < 0:
                        return False
                finally:
                    ole32.PropVariantClear(ctypes.byref(variant))
            return True
        finally:
            release(property_store)
    except Exception:
        return False
    finally:
        if should_uninitialize:
            ole32.CoUninitialize()


def bind_windows_taskbar_identity(
    config: DesktopLaunchConfig,
    *,
    platform_name: str | None = None,
    timeout_sec: float = 5.0,
    window_finder: Callable[[str], int] | None = None,
    property_setter: Callable[[int, Mapping[str, str]], bool] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> bool:
    """Bind the Chrome App HWND to the launcher identity used by the taskbar."""

    if (platform_name or sys.platform) != "win32":
        return False
    try:
        if window_finder is None:
            user32 = ctypes.windll.user32
            native_find_window = user32.FindWindowW
            native_find_window.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
            native_find_window.restype = ctypes.c_void_p
            window_finder = lambda title: int(native_find_window(None, title) or 0)
        apply_properties = property_setter or _set_windows_taskbar_window_properties
        deadline = time.monotonic() + max(0.0, float(timeout_sec))
        while True:
            window_handle = int(window_finder(APP_TITLE) or 0)
            if window_handle:
                return bool(
                    apply_properties(
                        window_handle,
                        windows_taskbar_relaunch_metadata(config),
                    )
                )
            if time.monotonic() >= deadline:
                return False
            sleeper(0.05)
    except Exception:
        return False


def start_windows_taskbar_identity_binding(
    config: DesktopLaunchConfig,
    *,
    platform_name: str | None = None,
) -> threading.Thread | None:
    """Bind a newly created Chrome window without delaying backend startup."""

    if (platform_name or sys.platform) != "win32":
        return None

    def worker() -> None:
        bound = bind_windows_taskbar_identity(config, platform_name="win32")
        write_launcher_log_event(
            config,
            "taskbar_identity_bound" if bound else "taskbar_identity_unavailable",
            app_user_model_id=WINDOWS_APP_USER_MODEL_ID,
        )

    thread = threading.Thread(
        target=worker,
        name="vp-taskbar-identity",
        daemon=True,
    )
    thread.start()
    return thread


def reset_launcher_log_if_oversized(
    log_path: Path,
    *,
    max_bytes: int = DEFAULT_LAUNCHER_LOG_MAX_BYTES,
) -> bool:
    """Discard oversized launcher output and remove obsolete rotated backups."""
    backup_path = log_path.with_name(f"{log_path.name}.1")
    try:
        backup_path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        if not log_path.is_file() or log_path.stat().st_size <= max(1, int(max_bytes)):
            return False
        log_path.unlink()
        return True
    except OSError:
        # Log maintenance must never prevent the desktop app from starting.
        return False


def write_launcher_log_event(
    config: DesktopLaunchConfig,
    event: str,
    **fields: object,
) -> None:
    payload = {"event": str(event or "launcher_event"), **fields}
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    line = f"{timestamp} [launcher] {json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n"
    try:
        config.log_path.parent.mkdir(parents=True, exist_ok=True)
        with config.log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
    except OSError:
        # Diagnostics are best effort and must not become a startup dependency.
        return


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((time.monotonic() - started_at) * 1000)))


def start_server(config: DesktopLaunchConfig) -> tuple[subprocess.Popen[bytes], object]:
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    reset_launcher_log_if_oversized(config.log_path)
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


def start_browser(
    config: DesktopLaunchConfig,
    *,
    app_url: str = "",
) -> subprocess.Popen[bytes]:
    config.browser_profile_dir.mkdir(parents=True, exist_ok=True)
    initialize_window = not config.window_initialized_marker.is_file()
    process = subprocess.Popen(
        build_browser_command(
            config,
            initialize_window=initialize_window,
            app_url=app_url,
        ),
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


def ensure_desktop_control_token(config: DesktopLaunchConfig) -> DesktopLaunchConfig:
    """Attach a stable local token used only by the Chrome App exit control."""

    token_path = config.desktop_control_token_path
    token_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    if len(token) < 32:
        token = secrets.token_urlsafe(32)
        temporary_path = token_path.with_suffix(".tmp")
        temporary_path.write_text(token + "\n", encoding="utf-8")
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        temporary_path.replace(token_path)
    return replace(config, desktop_control_token=token)


def _write_preparing_document(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(content, encoding="utf-8")
    try:
        temporary_path.replace(path)
    except PermissionError:
        # Chrome normally closes the file immediately after parsing. Retain a
        # direct-write fallback for managed Windows builds that deny replacement.
        path.write_text(content, encoding="utf-8")
        temporary_path.unlink(missing_ok=True)


def chrome_preparation_url(config: DesktopLaunchConfig) -> str:
    return config.desktop_preparing_path.resolve().as_uri()


def write_chrome_preparation_page(
    config: DesktopLaunchConfig,
    *,
    state: str,
    error: str = "",
) -> Path:
    normalized_state = str(state or "preparing").strip().lower()
    if normalized_state == "ready":
        state_script = (
            "window.__VP_PREPARING_TERMINAL__=true;"
            f"window.location.replace({json.dumps(config.chrome_desktop_url)});"
        )
        _write_preparing_document(config.desktop_preparing_state_path, state_script)
        return config.desktop_preparing_path
    if normalized_state == "failed":
        failure = str(error or f"See {config.log_path}").strip()
        state_script = f"window.vpPreparingFailed({json.dumps(failure)});"
        _write_preparing_document(config.desktop_preparing_state_path, state_script)
        return config.desktop_preparing_path

    icon_path = config.project_root / "app" / "static" / "assets" / "vintage_programmer.png"
    icon_markup = (
        f'<img class="mark" src="{escape(icon_path.resolve().as_uri())}" alt="">'
        if icon_path.is_file()
        else '<div class="mark fallback">VP</div>'
    )
    favicon_path = config.project_root / "app" / "static" / "assets" / "vintage_programmer.ico"
    favicon_source = favicon_path if favicon_path.is_file() else icon_path
    favicon_markup = (
        f'<link rel="icon" href="{escape(favicon_source.resolve().as_uri())}" sizes="any">'
        if favicon_source.is_file()
        else ""
    )
    heading = "Preparing…"
    spinner = '<span class="spinner" aria-hidden="true"></span>'
    document = f"""<!doctype html>
<html lang="en" translate="no" class="notranslate">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="google" content="notranslate">
  <title>{APP_TITLE}</title>
  {favicon_markup}
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; min-height: 100%; }}
    body {{
      min-height: 100vh; display: grid; place-items: center; color: #24211f;
      font-family: "Segoe UI", "PingFang SC", "Yu Gothic UI", sans-serif;
      background: linear-gradient(145deg, #fffaf5 0%, #f4f6f8 58%, #eef1f5 100%);
    }}
    main {{ display: grid; justify-items: center; gap: 14px; padding: 32px; text-align: center; }}
    .mark {{ width: 72px; height: 72px; object-fit: contain; }}
    .mark.fallback {{ display: grid; place-items: center; border-radius: 18px; background: #f37021; color: white; font-weight: 750; }}
    h1 {{ margin: 2px 0 0; font-size: 22px; letter-spacing: -0.02em; }}
    p {{ margin: 0; color: #6b625b; font-size: 14px; }}
    .spinner {{ width: 22px; height: 22px; margin-top: 4px; border: 2px solid rgba(243,112,33,.18); border-top-color: #f37021; border-radius: 50%; animation: spin .8s linear infinite; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  </style>
</head>
<body>
  <main role="status" aria-live="polite">
    {icon_markup}
    <h1 id="preparingHeading">{escape(heading)}</h1>
    <p id="preparingDetail" hidden></p>
    {spinner}
  </main>
  <script>
    window.__VP_PREPARING_TERMINAL__ = false;
    window.vpPreparingFailed = (message) => {{
      window.__VP_PREPARING_TERMINAL__ = true;
      document.getElementById("preparingHeading").textContent = "Startup failed";
      const detail = document.getElementById("preparingDetail");
      detail.textContent = String(message || "");
      detail.hidden = false;
      const spinner = document.querySelector(".spinner");
      if (spinner) spinner.remove();
    }};
    const pollState = () => {{
      if (window.__VP_PREPARING_TERMINAL__) return;
      const script = document.createElement("script");
      script.src = {json.dumps(config.desktop_preparing_state_path.name)} + "?check=" + Date.now();
      script.onload = script.onerror = () => {{
        script.remove();
        if (!window.__VP_PREPARING_TERMINAL__) window.setTimeout(pollState, 250);
      }};
      document.head.appendChild(script);
    }};
    pollState();
  </script>
</body>
</html>
"""
    _write_preparing_document(
        config.desktop_preparing_state_path,
        "window.__VP_PREPARING_STATE__='preparing';",
    )
    _write_preparing_document(config.desktop_preparing_path, document)
    return config.desktop_preparing_path


def stop_owned_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


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
    launch_started_at = time.monotonic()
    owned_server: subprocess.Popen[bytes] | None = None
    log_handle: object | None = None
    taskbar_identity_thread: threading.Thread | None = None
    chrome_window_started = False
    chrome_preparation_ready = False
    cold_launch_started = False
    lock_path = config.project_root / "app" / "data" / "runtime" / "desktop-launcher.lock"
    try:
        with startup_lock(lock_path):
            if not health_check(config.health_url):
                cold_launch_started = True
                previous_log_cleared = reset_launcher_log_if_oversized(config.log_path)
                session_dir = config.project_root / "app" / "data" / "sessions"
                session_count = sum(1 for _path in session_dir.glob("*.json")) if session_dir.is_dir() else 0
                write_launcher_log_event(
                    config,
                    "cold_launch_started",
                    elapsed_ms=_elapsed_ms(launch_started_at),
                    previous_log_cleared=previous_log_cleared,
                    session_count=session_count,
                )
                write_chrome_preparation_page(config, state="preparing")
                start_browser(config, app_url=chrome_preparation_url(config))
                chrome_window_started = True
                taskbar_identity_thread = start_windows_taskbar_identity_binding(config)
                write_launcher_log_event(
                    config,
                    "preparing_window_started",
                    elapsed_ms=_elapsed_ms(launch_started_at),
                )
                owned_server, log_handle = start_server(config)
                write_launcher_log_event(
                    config,
                    "backend_process_started",
                    elapsed_ms=_elapsed_ms(launch_started_at),
                    pid=getattr(owned_server, "pid", None),
                )
                health_wait_started_at = time.monotonic()
                if not wait_until_healthy(
                    config.health_url,
                    timeout_sec=config.startup_timeout_sec,
                    process=owned_server,
                ):
                    write_launcher_log_event(
                        config,
                        "backend_health_timeout",
                        elapsed_ms=_elapsed_ms(launch_started_at),
                        health_wait_ms=_elapsed_ms(health_wait_started_at),
                    )
                    failure = f"Vintage Programmer did not start. See the launcher log: {config.log_path}"
                    if chrome_window_started:
                        write_chrome_preparation_page(config, state="failed", error=failure)
                    raise LauncherError(failure)
                write_launcher_log_event(
                    config,
                    "backend_healthy",
                    elapsed_ms=_elapsed_ms(launch_started_at),
                    health_wait_ms=_elapsed_ms(health_wait_started_at),
                )
                if chrome_window_started:
                    write_chrome_preparation_page(config, state="ready")
                    chrome_preparation_ready = True
            elif focus_existing_desktop_window():
                if sys.platform == "win32":
                    taskbar_identity_bound = bind_windows_taskbar_identity(
                        config,
                        timeout_sec=0.25,
                    )
                    write_launcher_log_event(
                        config,
                        "taskbar_identity_bound" if taskbar_identity_bound else "taskbar_identity_unavailable",
                        app_user_model_id=WINDOWS_APP_USER_MODEL_ID,
                    )
                write_launcher_log_event(
                    config,
                    "existing_window_focused",
                    elapsed_ms=_elapsed_ms(launch_started_at),
                )
                return
        if not chrome_window_started:
            start_browser(config)
            if sys.platform == "win32":
                taskbar_identity_bound = bind_windows_taskbar_identity(config)
                write_launcher_log_event(
                    config,
                    "taskbar_identity_bound" if taskbar_identity_bound else "taskbar_identity_unavailable",
                    app_user_model_id=WINDOWS_APP_USER_MODEL_ID,
                )
            write_launcher_log_event(
                config,
                "existing_backend_window_started",
                elapsed_ms=_elapsed_ms(launch_started_at),
            )
    except BaseException as exc:
        write_launcher_log_event(
            config,
            "launch_failed",
            elapsed_ms=_elapsed_ms(launch_started_at),
            error=str(exc),
        )
        if chrome_window_started and not chrome_preparation_ready:
            write_chrome_preparation_page(config, state="failed", error=str(exc))
        if owned_server is not None:
            stop_owned_server(owned_server)
        raise
    finally:
        if taskbar_identity_thread is not None:
            taskbar_identity_thread.join(timeout=5.25)
        if log_handle is not None:
            close = getattr(log_handle, "close", None)
            if callable(close):
                close()
        if cold_launch_started:
            write_launcher_log_event(
                config,
                "cold_launch_finished",
                elapsed_ms=_elapsed_ms(launch_started_at),
                ready=chrome_preparation_ready,
            )


def restart_server_only(config: DesktopLaunchConfig) -> None:
    restart_started_at = time.monotonic()
    shutdown_timeout_sec = max(10.0, min(60.0, config.startup_timeout_sec))
    if not wait_until_stopped(config.health_url, timeout_sec=shutdown_timeout_sec):
        write_launcher_log_event(
            config,
            "restart_shutdown_timeout",
            elapsed_ms=_elapsed_ms(restart_started_at),
        )
        raise LauncherError("Vintage Programmer did not stop in time for restart.")

    lock_path = config.project_root / "app" / "data" / "runtime" / "desktop-launcher.lock"
    process: subprocess.Popen[bytes] | None = None
    log_handle: object | None = None
    try:
        with startup_lock(lock_path):
            if health_check(config.health_url):
                return
            previous_log_cleared = reset_launcher_log_if_oversized(config.log_path)
            write_launcher_log_event(
                config,
                "restart_started",
                elapsed_ms=_elapsed_ms(restart_started_at),
                previous_log_cleared=previous_log_cleared,
            )
            process, log_handle = start_server(config)
            health_wait_started_at = time.monotonic()
            if not wait_until_healthy(
                config.health_url,
                timeout_sec=config.startup_timeout_sec,
                process=process,
            ):
                write_launcher_log_event(
                    config,
                    "restart_health_timeout",
                    elapsed_ms=_elapsed_ms(restart_started_at),
                    health_wait_ms=_elapsed_ms(health_wait_started_at),
                )
                raise LauncherError(
                    f"Vintage Programmer did not restart. See the launcher log: {config.log_path}"
                )
            write_launcher_log_event(
                config,
                "restart_backend_healthy",
                elapsed_ms=_elapsed_ms(restart_started_at),
                health_wait_ms=_elapsed_ms(health_wait_started_at),
            )
    except BaseException as exc:
        write_launcher_log_event(
            config,
            "restart_failed",
            elapsed_ms=_elapsed_ms(restart_started_at),
            error=str(exc),
        )
        if process is not None:
            stop_owned_server(process)
        raise
    finally:
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
        description="Open Vintage Programmer in Google Chrome App Mode."
    )
    parser.add_argument("--project-root", default="", help="Vintage Programmer repository root")
    parser.add_argument("--browser-path", default="", help="Google Chrome executable path")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print configuration without launching")
    parser.add_argument("--diagnostics-file", default="", help="Write dry-run diagnostics to a JSON file")
    parser.add_argument(
        "--restart-server-only",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        set_windows_process_app_id()
        config = build_launch_config(
            project_root=args.project_root or None,
            browser_path=args.browser_path,
        )
        if args.dry_run:
            diagnostics = config.diagnostics()
            _write_diagnostics(diagnostics, args.diagnostics_file)
            return 0
        config = ensure_desktop_control_token(config)
        if args.restart_server_only:
            restart_server_only(config)
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
