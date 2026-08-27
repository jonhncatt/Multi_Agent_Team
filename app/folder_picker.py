from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Any


_WINDOWS_COMMON_FOLDER_PICKER_SCRIPT = r"""
$source = @'
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace VPFolderPicker
{
    [Flags]
    internal enum FileOpenOptions : uint
    {
        PickFolders = 0x00000020,
        ForceFileSystem = 0x00000040,
        PathMustExist = 0x00000800,
        FileMustExist = 0x00001000,
        DontAddToRecent = 0x02000000
    }

    internal enum ShellDisplayName : uint
    {
        FileSystemPath = 0x80058000
    }

    [ComImport]
    [Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")]
    internal class FileOpenDialogClass
    {
    }

    public static class NativeWindow
    {
        private delegate bool EnumWindowsProc(IntPtr window, IntPtr parameter);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr FindWindow(string className, string windowName);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr parameter);

        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr window);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetWindowText(IntPtr window, StringBuilder title, int maxCount);

        public static IntPtr FindVintageProgrammer()
        {
            IntPtr exact = FindWindow(null, "Vintage Programmer");
            if (exact != IntPtr.Zero)
            {
                return exact;
            }

            IntPtr match = IntPtr.Zero;
            EnumWindows(delegate (IntPtr window, IntPtr parameter)
            {
                if (!IsWindowVisible(window)) return true;
                StringBuilder title = new StringBuilder(512);
                GetWindowText(window, title, title.Capacity);
                if (title.ToString().Contains("Vintage Programmer"))
                {
                    match = window;
                    return false;
                }
                return true;
            }, IntPtr.Zero);
            return match;
        }
    }

    [ComImport]
    [Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IShellItem
    {
        void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
        void GetParent(out IShellItem parent);
        void GetDisplayName(ShellDisplayName sigdnName, out IntPtr name);
        void GetAttributes(uint mask, out uint attributes);
        void Compare(IShellItem other, uint hint, out int order);
    }

    [ComImport]
    [Guid("D57C7288-D4AD-4768-BE02-9D969532D960")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IFileOpenDialog
    {
        [PreserveSig] int Show(IntPtr owner);
        void SetFileTypes(uint count, IntPtr filterSpec);
        void SetFileTypeIndex(uint index);
        void GetFileTypeIndex(out uint index);
        void Advise(IntPtr events, out uint cookie);
        void Unadvise(uint cookie);
        void SetOptions(FileOpenOptions options);
        void GetOptions(out FileOpenOptions options);
        void SetDefaultFolder(IShellItem folder);
        void SetFolder(IShellItem folder);
        void GetFolder(out IShellItem folder);
        void GetCurrentSelection(out IShellItem item);
        void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
        void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string name);
        void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
        void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
        void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
        void GetResult(out IShellItem item);
        void AddPlace(IShellItem item, uint alignment);
        void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string extension);
        void Close(int result);
        void SetClientGuid(ref Guid guid);
        void ClearClientData();
        void SetFilter(IntPtr filter);
        void GetResults(out IntPtr items);
        void GetSelectedItems(out IntPtr items);
    }

    public static class CommonFolderDialog
    {
        private const int Cancelled = unchecked((int)0x800704C7);

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        private static extern int SHCreateItemFromParsingName(
            [MarshalAs(UnmanagedType.LPWStr)] string path,
            IntPtr bindingContext,
            ref Guid interfaceId,
            [MarshalAs(UnmanagedType.Interface)] out IShellItem item);

        public static string Show(string initialPath, IntPtr owner)
        {
            IFileOpenDialog dialog = (IFileOpenDialog)new FileOpenDialogClass();
            IShellItem initialFolder = null;
            IShellItem selectedFolder = null;
            try
            {
                FileOpenOptions options;
                dialog.GetOptions(out options);
                options |= FileOpenOptions.PickFolders
                    | FileOpenOptions.ForceFileSystem
                    | FileOpenOptions.PathMustExist
                    | FileOpenOptions.DontAddToRecent;
                options &= ~FileOpenOptions.FileMustExist;
                dialog.SetOptions(options);
                dialog.SetTitle("Select a project folder");
                dialog.SetOkButtonLabel("Select Folder");

                if (!String.IsNullOrWhiteSpace(initialPath))
                {
                    Guid shellItemId = typeof(IShellItem).GUID;
                    int initialResult = SHCreateItemFromParsingName(
                        initialPath,
                        IntPtr.Zero,
                        ref shellItemId,
                        out initialFolder);
                    if (initialResult >= 0 && initialFolder != null)
                    {
                        dialog.SetDefaultFolder(initialFolder);
                    }
                }

                int showResult = dialog.Show(owner);
                if (showResult == Cancelled)
                {
                    return null;
                }
                if (showResult < 0)
                {
                    Marshal.ThrowExceptionForHR(showResult);
                }

                dialog.GetResult(out selectedFolder);
                IntPtr displayName = IntPtr.Zero;
                try
                {
                    selectedFolder.GetDisplayName(ShellDisplayName.FileSystemPath, out displayName);
                    return displayName == IntPtr.Zero ? null : Marshal.PtrToStringUni(displayName);
                }
                finally
                {
                    if (displayName != IntPtr.Zero)
                    {
                        Marshal.FreeCoTaskMem(displayName);
                    }
                }
            }
            finally
            {
                if (selectedFolder != null) Marshal.FinalReleaseComObject(selectedFolder);
                if (initialFolder != null) Marshal.FinalReleaseComObject(initialFolder);
                if (dialog != null) Marshal.FinalReleaseComObject(dialog);
            }
        }
    }
}
'@

$exitCode = 2
try {
    Add-Type -TypeDefinition $source -Language CSharp
    $ownerHandle = [VPFolderPicker.NativeWindow]::FindVintageProgrammer()
    $selected = [VPFolderPicker.CommonFolderDialog]::Show(
        $env:VP_FOLDER_PICKER_INITIAL,
        $ownerHandle
    )
    if (-not [String]::IsNullOrWhiteSpace($selected)) {
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        Write-Output $selected
        $exitCode = 0
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.ToString())
    $exitCode = 3
}
exit $exitCode
"""


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
        completed = subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-STA",
                "-Command",
                _WINDOWS_COMMON_FOLDER_PICKER_SCRIPT,
            ],
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
