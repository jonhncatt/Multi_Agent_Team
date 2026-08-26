from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Any


def _initial_directory(raw: str) -> Path:
    candidate = Path(str(raw or "").strip()).expanduser() if str(raw or "").strip() else Path.home()
    try:
        resolved = candidate.resolve(strict=False)
    except OSError:
        return Path.home().resolve()
    return resolved if resolved.exists() and resolved.is_dir() else Path.home().resolve()


def _selected_payload(stdout: str) -> dict[str, Any]:
    lines = [line.strip() for line in str(stdout or "").splitlines() if line.strip()]
    if not lines:
        return {
            "ok": False,
            "path": "",
            "cancelled": False,
            "supported": True,
            "message": "The folder picker returned no path.",
        }
    selected = Path(lines[-1]).expanduser().resolve(strict=False)
    if not selected.exists() or not selected.is_dir():
        return {
            "ok": False,
            "path": "",
            "cancelled": False,
            "supported": True,
            "message": "The selected folder is not available.",
        }
    return {
        "ok": True,
        "path": str(selected),
        "cancelled": False,
        "supported": True,
        "message": "Folder selected.",
    }


def _cancelled_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "path": "",
        "cancelled": True,
        "supported": True,
        "message": "Folder selection was cancelled.",
    }


def _unsupported_payload(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "path": "",
        "cancelled": False,
        "supported": False,
        "message": str(message or "System folder picker is unavailable."),
    }


def choose_system_folder(initial_path: str = "", *, platform_name: str = "") -> dict[str, Any]:
    """Open the host operating system's folder picker and return an absolute path."""
    system = str(platform_name or platform.system() or "").strip().lower()
    initial = _initial_directory(initial_path)
    env = os.environ.copy()
    env["VP_FOLDER_PICKER_INITIAL"] = str(initial)

    if system.startswith("win"):
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if not powershell:
            return _unsupported_payload("Windows PowerShell is unavailable, so the folder picker cannot open.")
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dialog.Description = 'Select a project folder'; "
            "$dialog.ShowNewFolderButton = $true; "
            "if (Test-Path -LiteralPath $env:VP_FOLDER_PICKER_INITIAL -PathType Container) "
            "{ $dialog.SelectedPath = $env:VP_FOLDER_PICKER_INITIAL }; "
            "$result = $dialog.ShowDialog(); "
            "if ($result -eq [System.Windows.Forms.DialogResult]::OK) "
            "{ [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Write-Output $dialog.SelectedPath; exit 0 }; "
            "exit 2"
        )
        completed = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
            text=True,
            capture_output=True,
            env=env,
            check=False,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0),
        )
    elif system in {"darwin", "mac", "macos"}:
        osascript = shutil.which("osascript") or "/usr/bin/osascript"
        if not Path(osascript).exists():
            return _unsupported_payload("macOS osascript is unavailable, so the folder picker cannot open.")
        script = (
            "on run argv\n"
            "set initialFolder to POSIX file (item 1 of argv) as alias\n"
            'return POSIX path of (choose folder with prompt "Select a project folder" '
            "default location initialFolder)\n"
            "end run"
        )
        completed = subprocess.run(
            [osascript, "-e", script, str(initial)],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
    else:
        zenity = shutil.which("zenity")
        kdialog = shutil.which("kdialog")
        if zenity:
            argv = [zenity, "--file-selection", "--directory", "--filename", f"{initial}{os.sep}"]
        elif kdialog:
            argv = [kdialog, "--getexistingdirectory", str(initial)]
        else:
            return _unsupported_payload("No supported Linux folder picker (zenity or kdialog) is installed.")
        completed = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    if int(completed.returncode) == 0:
        return _selected_payload(completed.stdout)
    stderr = str(completed.stderr or "").strip()
    if int(completed.returncode) in {1, 2} or "cancel" in stderr.lower():
        return _cancelled_payload()
    return {
        "ok": False,
        "path": "",
        "cancelled": False,
        "supported": True,
        "message": stderr or "The system folder picker could not be opened.",
    }
