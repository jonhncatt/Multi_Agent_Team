# Validation Assistant Windows Desktop Launcher

This lightweight launcher starts the existing `app.main:app` FastAPI server and
opens it in Google Chrome App Mode. It provides a standalone window without the
normal address bar or tabs while leaving Agent Runtime behavior unchanged.

## Use a CI build

1. Download `validation-assistant-windows-launcher` from the **Windows Desktop
   Launcher** GitHub Actions workflow.
2. Put `ValidationAssistant.exe` in the repository root next to `requirements.txt`.
3. Complete the normal Windows setup in `README.windows.md`, including `.venv`
   and `.env`.
4. Make sure Google Chrome is installed, then double-click the executable.

The launcher has no console window. Startup failures are shown in a message box
and written to `app/data/runtime/desktop-launcher.log`. Routine HTTP access
lines are disabled; when the log exceeds 2 MiB on the next launch, it is
cleared before the new launch is recorded. Launcher log backups are not kept.

The packaged launcher checks only the directory containing the executable. It
does not search parent directories or other checkouts. That directory must also
contain `app/main.py`, `requirements.txt`, and `desktop/launcher.py`. Use
`VA_DESKTOP_PROJECT_ROOT` only when intentionally binding an explicit location.

When a new backend is required, Chrome opens immediately on a local `Preparing…`
page and moves to Validation Assistant when `/api/health` is ready. The later
`Loading workspace…` state covers only project, Thread, and local-setting loading.

Launching the executable again first restores an existing Validation Assistant
window. If the Chrome window was closed while the backend remained active, a new
window is opened against that same backend instead.

The launcher assigns the Chrome App window and the launcher a shared Windows
AppUserModelID. On the first build containing this support, unpin the old direct
EXE taskbar item, launch the new `ValidationAssistant.exe`, then pin the running VA
window. That one-time re-pin stores the VA relaunch command and high-resolution
icon; later launches still go through the EXE so the backend is prepared before
Chrome App Mode opens.

The executable and Windows taskbar identity use a multi-size DIB icon derived
from the same yellow-orange-red gradient artwork, with a firmer transparent edge
for reliable Windows Shell extraction. The Chrome title-bar favicon uses the
matching PNG-based gradient icon. The Windows build verifies that Shell can
extract both large and small EXE icons before the launcher is published.

Use the **Exit** button in the top-right navigation to stop active work and the
local backend before closing. Chrome's ordinary window close cannot reliably
report its lifecycle to the launcher, so closing with `X` leaves the backend
running. Starting the executable again reopens the window in that case.

After a manual repository update succeeds, the desktop window offers **Close**
and **Restart VA now**. Restarting keeps the current window open, replaces the
local backend without opening a console window, shows a Preparing-style waiting
screen, and reloads the page automatically when the new process is ready.

## Build on Windows

```powershell
desktop\windows\build.ps1
```

The executable is written to `dist\ValidationAssistant.exe`.
Copy it to the repository root before launching it; the build output directory is
not treated as the application root.

## Preview on macOS

The same Chrome App Mode launcher can be previewed on macOS:

```bash
./.venv/bin/python -m desktop.launcher
```

## Configuration

The desktop window uses a Chrome profile separate from the Agent browser. Do not
point `VA_DESKTOP_BROWSER_USER_DATA_DIR` at `VA_BROWSER_USER_DATA_DIR`.

```env
VA_DESKTOP_SHELL=chrome
VA_DESKTOP_BROWSER_PATH=
VA_DESKTOP_BROWSER_USER_DATA_DIR=app/data/desktop_browser_profile
VA_DESKTOP_STARTUP_TIMEOUT_SEC=45
VA_DESKTOP_INITIAL_WINDOW_SIZE=1360,840
VA_DESKTOP_UI_SCALE=0.8
```

`VA_DESKTOP_SHELL=auto` remains accepted for compatibility and behaves exactly
like `chrome`. Other values are rejected. Chrome is auto-detected when
`VA_DESKTOP_BROWSER_PATH` is empty.

The first window opens maximized and Chrome remembers later resizing. The
desktop-only UI scale defaults to 80%; set it between `0.65` and `1.25` for a
particular Windows display or DPI setting. It does not change the regular web UI.
