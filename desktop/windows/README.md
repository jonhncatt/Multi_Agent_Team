# Vintage Programmer Windows Desktop Launcher

This lightweight launcher starts the existing `app.main:app` FastAPI server and
opens it in Google Chrome App Mode. It provides a standalone window without the
normal address bar or tabs while leaving Agent Runtime behavior unchanged.

## Use a CI build

1. Download `vintage-programmer-windows-launcher` from the **Windows Desktop
   Launcher** GitHub Actions workflow.
2. Put `VintageProgrammer.exe` in the repository root next to `requirements.txt`.
3. Complete the normal Windows setup in `README.windows.md`, including `.venv`
   and `.env`.
4. Make sure Google Chrome is installed, then double-click the executable.

The launcher has no console window. Startup failures are shown in a message box
and written to `app/data/runtime/desktop-launcher.log`.

The packaged launcher checks only the directory containing the executable. It
does not search parent directories or other checkouts. That directory must also
contain `app/main.py`, `requirements.txt`, and `desktop/launcher.py`. Use
`VP_DESKTOP_PROJECT_ROOT` only when intentionally binding an explicit location.

When a new backend is required, Chrome opens immediately on a local `Preparing…`
page and moves to Vintage Programmer when `/api/health` is ready. The later
`Loading workspace…` state covers only project, Thread, and local-setting loading.

Launching the executable again first restores an existing Vintage Programmer
window. If the Chrome window was closed while the backend remained active, a new
window is opened against that same backend instead.

Use the **Exit** button in the top-right navigation to stop active work and the
local backend before closing. Chrome's ordinary window close cannot reliably
report its lifecycle to the launcher, so closing with `X` leaves the backend
running. Starting the executable again reopens the window in that case.

After a manual repository update succeeds, the desktop window offers **Close**
and **Restart VP now**. Restarting keeps the current window open, replaces the
local backend, and reloads the page automatically when the new process is ready.

## Build on Windows

```powershell
desktop\windows\build.ps1
```

The executable is written to `dist\VintageProgrammer.exe`.
Copy it to the repository root before launching it; the build output directory is
not treated as the application root.

## Preview on macOS

The same Chrome App Mode launcher can be previewed on macOS:

```bash
./.venv/bin/python -m desktop.launcher
```

## Configuration

The desktop window uses a Chrome profile separate from the Agent browser. Do not
point `VP_DESKTOP_BROWSER_USER_DATA_DIR` at `VP_BROWSER_USER_DATA_DIR`.

```env
VP_DESKTOP_SHELL=chrome
VP_DESKTOP_BROWSER_PATH=
VP_DESKTOP_BROWSER_USER_DATA_DIR=app/data/desktop_browser_profile
VP_DESKTOP_STARTUP_TIMEOUT_SEC=45
VP_DESKTOP_INITIAL_WINDOW_SIZE=1360,840
VP_DESKTOP_UI_SCALE=0.8
```

`VP_DESKTOP_SHELL=auto` remains accepted for compatibility and behaves exactly
like `chrome`. Other values are rejected. Chrome is auto-detected when
`VP_DESKTOP_BROWSER_PATH` is empty.

The first window opens maximized and Chrome remembers later resizing. The
desktop-only UI scale defaults to 80%; set it between `0.65` and `1.25` for a
particular Windows display or DPI setting. It does not change the regular web UI.
