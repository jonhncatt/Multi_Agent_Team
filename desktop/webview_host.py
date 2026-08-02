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


def close_dialog_copy(locale: str, active_count: int) -> tuple[str, str, str]:
    count = max(1, int(active_count or 1))
    normalized = str(locale or "").strip().lower()
    if normalized.startswith("zh"):
        return (
            f"Agent 仍有 {count} 个任务正在运行。关闭前将停止正在执行的任务。",
            "停止任务并完全退出",
            "取消关闭",
        )
    if normalized.startswith("ja"):
        return (
            f"Agent で {count} 件のタスクが実行中です。終了する前に実行中のタスクを停止します。",
            "タスクを停止して完全に終了",
            "終了をキャンセル",
        )
    return (
        f"Agent still has {count} running task(s). Running work will be stopped before exit.",
        "Stop tasks and exit",
        "Cancel closing",
    )


def confirm_stop_and_exit(
    owner_window: Any,
    *,
    active_count: int,
    locale: str,
) -> bool:
    """Show a safe, native two-choice dialog for closing an active desktop run."""

    message, stop_label, cancel_label = close_dialog_copy(locale, active_count)
    dialog = None
    try:
        from System.Drawing import Size  # type: ignore[import-not-found]
        from System.Windows.Forms import (  # type: ignore[import-not-found]
            Button,
            DialogResult,
            Form,
            FormBorderStyle,
            FormStartPosition,
            Label,
        )

        dialog = Form()
        dialog.Text = "Vintage Programmer"
        dialog.ClientSize = Size(560, 168)
        dialog.FormBorderStyle = FormBorderStyle.FixedDialog
        dialog.StartPosition = FormStartPosition.CenterParent
        dialog.MaximizeBox = False
        dialog.MinimizeBox = False
        dialog.ShowInTaskbar = False

        label = Label()
        label.Text = message
        label.AutoSize = False
        label.SetBounds(24, 22, 512, 58)

        stop_button = Button()
        stop_button.Text = stop_label
        stop_button.DialogResult = DialogResult.Yes
        stop_button.SetBounds(178, 102, 220, 38)

        cancel_button = Button()
        cancel_button.Text = cancel_label
        cancel_button.DialogResult = DialogResult.Cancel
        cancel_button.SetBounds(410, 102, 126, 38)

        dialog.Controls.Add(label)
        dialog.Controls.Add(stop_button)
        dialog.Controls.Add(cancel_button)
        dialog.AcceptButton = cancel_button
        dialog.CancelButton = cancel_button
        dialog.ActiveControl = cancel_button

        native_owner = getattr(owner_window, "native", None)
        result = dialog.ShowDialog(native_owner) if native_owner is not None else dialog.ShowDialog()
        return result == DialogResult.Yes
    except Exception:
        # WinForms is bundled with the Windows host, but retain a native safe-default
        # fallback in case a host-specific owner cannot be attached to the custom form.
        flags = 0x00000004 | 0x00000030 | 0x00000100  # YESNO | ICONWARNING | DEFBUTTON2
        return int(ctypes.windll.user32.MessageBoxW(None, message, "Vintage Programmer", flags)) == 6
    finally:
        if dialog is not None:
            try:
                dialog.Dispose()
            except Exception:
                pass


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
    closing_handler: Callable[[Any], bool] | None = None,
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

        def handle_closing() -> bool:
            if closing_handler is None:
                return True
            try:
                return bool(closing_handler(window))
            except Exception:
                # Closing is a destructive boundary. Any lifecycle check failure
                # keeps the window open instead of accidentally killing active work.
                return False

        window.events.initialized += record_renderer
        window.events.before_show += apply_branding
        window.events.closing += handle_closing
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
