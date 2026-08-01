from __future__ import annotations

import ctypes
from pathlib import Path
import sys
from typing import Any, Callable


APP_USER_MODEL_ID = "VintageProgrammer.Desktop"


class WebViewHostError(RuntimeError):
    """Raised when the native Windows WebView2 shell cannot be started."""


def probe_webview2_host(*, platform_name: str | None = None) -> dict[str, str | bool]:
    if (platform_name or sys.platform) != "win32":
        return {
            "available": False,
            "renderer": "",
            "reason": "WebView2 is available only on Windows.",
        }
    try:
        import webview  # noqa: F401
        from webview.platforms import winforms

        renderer = str(getattr(winforms, "renderer", "") or "").strip().lower()
        if renderer != "edgechromium":
            return {
                "available": False,
                "renderer": renderer,
                "reason": "Microsoft Edge WebView2 Runtime was not detected.",
            }
        return {"available": True, "renderer": renderer, "reason": ""}
    except Exception as exc:
        return {"available": False, "renderer": "", "reason": str(exc)}


def bundled_asset_path(project_root: Path, relative_path: str) -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        bundled = Path(str(bundle_root)) / relative_path
        if bundled.is_file():
            return bundled
    return project_root / relative_path


def set_windows_app_identity(
    *,
    platform_name: str | None = None,
    setter: Callable[[str], int] | None = None,
) -> None:
    if (platform_name or sys.platform) != "win32":
        return
    identity_setter = setter
    if identity_setter is None:
        identity_setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    result = int(identity_setter(APP_USER_MODEL_ID))
    if result != 0:
        raise WebViewHostError(f"Windows rejected the application identity ({result}).")


def _apply_windows_window_icon(window: Any, icon_path: Path) -> None:
    if not icon_path.is_file():
        return
    try:
        from System.Drawing import Icon  # type: ignore[import-not-found]

        window.native.Icon = Icon(str(icon_path))
    except Exception:
        # The executable resource still supplies the taskbar icon. This explicit
        # native assignment is a best-effort fallback for unfrozen development.
        return


def open_webview2_window(
    *,
    url: str,
    project_root: Path,
    profile_dir: Path,
    width: int,
    height: int,
    platform_name: str | None = None,
    webview_module: Any | None = None,
    app_identity_setter: Callable[[str], int] | None = None,
    icon_applier: Callable[[Any, Path], None] = _apply_windows_window_icon,
) -> None:
    if (platform_name or sys.platform) != "win32":
        raise WebViewHostError("The WebView2 desktop shell is available only on Windows.")

    set_windows_app_identity(platform_name="win32", setter=app_identity_setter)
    if webview_module is None:
        try:
            import webview as webview_module  # type: ignore[no-redef]
        except Exception as exc:
            raise WebViewHostError(f"The native WebView host is unavailable: {exc}") from exc

    profile_dir.mkdir(parents=True, exist_ok=True)
    icon_path = bundled_asset_path(
        project_root,
        "desktop/windows/assets/vintage_programmer.ico",
    )
    renderer: dict[str, str] = {"name": ""}

    try:
        webview_module.settings["ALLOW_DOWNLOADS"] = True
        webview_module.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        window = webview_module.create_window(
            "Vintage Programmer",
            url,
            width=width,
            height=height,
            min_size=(900, 600),
            resizable=True,
            maximized=True,
            background_color="#f7f8fa",
            text_select=True,
        )

        def record_renderer(renderer_name: str) -> bool:
            renderer["name"] = str(renderer_name or "").strip().lower()
            return renderer["name"] == "edgechromium"

        def apply_branding() -> None:
            icon_applier(window, icon_path)

        window.events.initialized += record_renderer
        window.events.before_show += apply_branding
        webview_module.start(
            gui="edgechromium",
            private_mode=False,
            storage_path=str(profile_dir),
            icon=str(icon_path) if icon_path.is_file() else None,
        )
    except Exception as exc:
        raise WebViewHostError(f"WebView2 could not open the desktop window: {exc}") from exc

    if renderer["name"] != "edgechromium":
        raise WebViewHostError(
            "Microsoft Edge WebView2 Runtime is unavailable; the native window was not opened."
        )
