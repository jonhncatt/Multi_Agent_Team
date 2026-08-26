from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import app.folder_picker as folder_picker


def test_windows_folder_picker_returns_selected_directory_without_console(monkeypatch, tmp_path: Path) -> None:
    selected = tmp_path / "项目"
    selected.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr(folder_picker.shutil, "which", lambda name: "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe" if name == "powershell" else None)
    monkeypatch.setattr(folder_picker.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout=f"{selected}\n", stderr="")

    monkeypatch.setattr(folder_picker.subprocess, "run", fake_run)

    payload = folder_picker.choose_system_folder(str(tmp_path), platform_name="Windows")

    assert payload == {
        "ok": True,
        "path": str(selected.resolve()),
        "cancelled": False,
        "supported": True,
        "message": "Folder selected.",
    }
    assert captured["argv"][0].endswith("powershell.exe")
    assert "-STA" in captured["argv"]
    script = captured["argv"][-1]
    assert "$owner.TopMost = $true" in script
    assert "$dialog.ShowDialog($owner)" in script
    assert captured["creationflags"] == 0x08000000
    assert captured["env"]["VP_FOLDER_PICKER_INITIAL"] == str(tmp_path.resolve())


def test_macos_folder_picker_cancel_is_not_an_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(folder_picker.shutil, "which", lambda name: "/usr/bin/osascript" if name == "osascript" else None)
    monkeypatch.setattr(folder_picker.Path, "exists", lambda _self: True)
    monkeypatch.setattr(
        folder_picker.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="execution error: User canceled. (-128)",
        ),
    )

    payload = folder_picker.choose_system_folder(str(tmp_path), platform_name="macOS")

    assert payload["ok"] is True
    assert payload["cancelled"] is True
    assert payload["path"] == ""


def test_linux_folder_picker_reports_when_no_native_dialog_is_available(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(folder_picker.shutil, "which", lambda _name: None)

    payload = folder_picker.choose_system_folder(str(tmp_path), platform_name="Linux")

    assert payload["ok"] is False
    assert payload["supported"] is False
    assert "zenity or kdialog" in payload["message"]


def test_folder_picker_rejects_a_non_directory_result(monkeypatch, tmp_path: Path) -> None:
    selected_file = tmp_path / "not-a-folder.txt"
    selected_file.write_text("x", encoding="utf-8")
    monkeypatch.setattr(folder_picker.shutil, "which", lambda name: "/usr/bin/zenity" if name == "zenity" else None)
    monkeypatch.setattr(
        folder_picker.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=f"{selected_file}\n", stderr=""),
    )

    payload = folder_picker.choose_system_folder(str(tmp_path), platform_name="Linux")

    assert payload["ok"] is False
    assert payload["cancelled"] is False
    assert payload["message"] == "The selected folder is not available."
