from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys


def verify_executable_icon(path: Path) -> None:
    if sys.platform != "win32":
        raise SystemExit("Executable icon verification requires Windows.")
    executable = path.expanduser().resolve()
    if not executable.is_file():
        raise SystemExit(f"Executable was not found: {executable}")

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32.ExtractIconExW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_int,
        ctypes.POINTER(wintypes.HICON),
        ctypes.POINTER(wintypes.HICON),
        wintypes.UINT,
    ]
    shell32.ExtractIconExW.restype = wintypes.UINT
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.DestroyIcon.restype = wintypes.BOOL

    large_icons = (wintypes.HICON * 1)()
    small_icons = (wintypes.HICON * 1)()
    extracted = int(
        shell32.ExtractIconExW(
            str(executable),
            0,
            large_icons,
            small_icons,
            1,
        )
    )
    try:
        if extracted < 1 or not large_icons[0] or not small_icons[0]:
            error = ctypes.get_last_error()
            raise SystemExit(
                f"Windows Shell could not extract both EXE icon sizes (error={error})."
            )
    finally:
        for handle in (large_icons[0], small_icons[0]):
            if handle:
                user32.DestroyIcon(handle)

    print(f"Windows Shell extracted large and small icons: {executable}")
