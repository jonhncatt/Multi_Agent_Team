# Vintage Programmer Windows Desktop Launcher

This launcher does not replace or modify the Agent Runtime. It starts the existing
`app.main:app` server, waits for `/api/health`, and opens that server in a native
Windows window backed by Microsoft Edge WebView2. The window has its own VP process,
application identity, profile, and icon. If WebView2 is unavailable, automatic mode
falls back to Chrome App Mode.

## Use a CI build

1. Download the `vintage-programmer-windows-launcher` artifact from the
   **Windows Desktop Launcher** GitHub Actions workflow.
2. Put `VintageProgrammer.exe` in the root of the Vintage Programmer checkout,
   next to `requirements.txt`.
3. Complete the normal Windows setup in `README.windows.md`, including `.venv`
   and `.env`.
4. Double-click `VintageProgrammer.exe`.

The launcher has no console window. Startup failures are shown in a message box
and written to `app/data/runtime/desktop-launcher.log`.

The WebView2 host is single-instance. Double-clicking the executable while its window
is open restores the existing window instead of opening another backend or window.
Closing an idle native window also stops the local VP backend. If an Agent or Eval is
still running, the close dialog offers only **Stop tasks and exit** or **Cancel
closing**. Agent cancellation uses the normal runtime cancel path before the backend
exits. Chrome App Mode remains a compatibility fallback and cannot provide the same
native window-lifecycle guarantees.

## Build on Windows

```powershell
desktop\windows\build.ps1
```

The executable is written to `dist\VintageProgrammer.exe`.

## Preview on macOS

WebView2 is Windows-only. The same launcher core uses Chrome App Mode for a close
layout and lifecycle preview on macOS:

```bash
./.venv/bin/python -m desktop.launcher
```

## Configuration

Both desktop shells intentionally use profiles separate from the Agent browser.
Do not point any desktop profile at `VP_BROWSER_USER_DATA_DIR`.

```env
# Optional; Chrome is auto-detected and Edge is used as a fallback.
VP_DESKTOP_SHELL=auto
VP_DESKTOP_BROWSER_PATH=
VP_DESKTOP_BROWSER_USER_DATA_DIR=app/data/desktop_browser_profile
VP_DESKTOP_WEBVIEW2_USER_DATA_DIR=app/data/desktop_webview2_profile
VP_DESKTOP_STARTUP_TIMEOUT_SEC=45
VP_DESKTOP_CLOSE_TIMEOUT_SEC=5
VP_DESKTOP_INITIAL_WINDOW_SIZE=1360,840
VP_DESKTOP_UI_SCALE=0.8
```

`auto` prefers WebView2 on Windows and falls back to Chrome. Use `webview2` to require
the native host or `chrome` to force the legacy App Mode window. The native window
opens maximized; Chrome uses the configured size on first launch and remembers later
resizing.
The desktop-only UI scale defaults to 80% to keep the workspace density close to
the regular browser view. Set it between `0.65` and `1.25` if a particular Windows
display or DPI setting needs a different density. It does not change the web UI.

`VP_BROWSER_USER_DATA_DIR` remains reserved for the Agent's Playwright/Redmine
browser session; WebView2 never replaces that automation browser.
