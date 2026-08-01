# Vintage Programmer Windows Desktop Launcher

This launcher does not replace or modify the Agent Runtime. It starts the existing
`app.main:app` server, waits for `/api/health`, and opens that server in Chrome App
Mode. Google Chrome is preferred and Microsoft Edge is the fallback.

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

After the window opens, the launcher exits and leaves the existing VP backend
lifecycle unchanged. Closing the Chrome App Mode window therefore does not cancel a
running Agent; double-clicking the executable again reconnects to the same backend.

## Build on Windows

```powershell
desktop\windows\build.ps1
```

The executable is written to `dist\VintageProgrammer.exe`.

## Preview on macOS

The same launcher core can be used to inspect Chrome App Mode before producing a
Windows build:

```bash
./.venv/bin/python -m desktop.launcher
```

## Configuration

The desktop shell intentionally uses a different Chrome profile from Agent browser
tools. Do not point both settings at the same directory.

```env
# Optional; Chrome is auto-detected and Edge is used as a fallback.
VP_DESKTOP_BROWSER_PATH=
VP_DESKTOP_BROWSER_USER_DATA_DIR=app/data/desktop_browser_profile
VP_DESKTOP_STARTUP_TIMEOUT_SEC=45
```

`VP_BROWSER_USER_DATA_DIR` remains reserved for the Agent's Playwright/Redmine
browser session.
