from __future__ import annotations

import struct
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _ico_sizes(payload: bytes) -> set[tuple[int, int]]:
    assert payload[:4] == b"\x00\x00\x01\x00"
    count = int.from_bytes(payload[4:6], "little")
    sizes: set[tuple[int, int]] = set()
    for index in range(count):
        entry = payload[6 + (index * 16) : 22 + (index * 16)]
        assert len(entry) == 16
        width = entry[0] or 256
        height = entry[1] or 256
        image_size = int.from_bytes(entry[8:12], "little")
        image_offset = int.from_bytes(entry[12:16], "little")
        assert payload[image_offset : image_offset + 8] == b"\x89PNG\r\n\x1a\n"
        assert image_offset + image_size <= len(payload)
        sizes.add((width, height))
    return sizes


def _png_size(path: Path) -> tuple[int, int]:
    payload = path.read_bytes()
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    assert payload[12:16] == b"IHDR"
    return struct.unpack(">II", payload[16:24])


def test_windows_build_embeds_multisize_vp_icon_without_webview2() -> None:
    asset_dir = REPO_ROOT / "desktop" / "windows" / "assets"
    icon = (asset_dir / "vintage_programmer.ico").read_bytes()
    png = (asset_dir / "vintage_programmer.png").read_bytes()
    master = (asset_dir / "vintage_programmer_master.png").read_bytes()
    web_png = (
        REPO_ROOT / "app" / "static" / "assets" / "vintage_programmer.png"
    ).read_bytes()
    web_icon = (
        REPO_ROOT / "app" / "static" / "assets" / "vintage_programmer.ico"
    ).read_bytes()
    web_small_icons = [
        REPO_ROOT / "app" / "static" / "assets" / f"vintage_programmer_{size}.png"
        for size in (16, 32, 48, 64)
    ]
    build_script = (REPO_ROOT / "desktop" / "windows" / "build.ps1").read_text(
        encoding="utf-8"
    )
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "windows-desktop-launcher.yml"
    ).read_text(encoding="utf-8")
    requirements = (
        REPO_ROOT / "desktop" / "windows" / "requirements-build.txt"
    ).read_text(encoding="utf-8")

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert master.startswith(b"\x89PNG\r\n\x1a\n")
    assert web_png == png
    assert web_icon == icon
    assert all(
        path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        for path in web_small_icons
    )
    assert icon[:4] == b"\x00\x00\x01\x00"
    assert int.from_bytes(icon[4:6], "little") == 9
    assert "--icon desktop\\windows\\assets\\vintage_programmer.ico" in build_script
    assert "--icon desktop/windows/assets/vintage_programmer.ico" in workflow
    assert "Start-Process" in workflow
    assert "-Wait" in workflow
    assert "if ($launcher.ExitCode -ne 0)" in workflow
    assert "pywebview" not in requirements.lower()
    assert not (REPO_ROOT / "desktop" / "webview_host.py").exists()


def test_windows_icon_contains_native_frames_for_small_taskbar_sizes() -> None:
    asset_dir = REPO_ROOT / "desktop" / "windows" / "assets"
    web_asset_dir = REPO_ROOT / "app" / "static" / "assets"
    icon_payload = (asset_dir / "vintage_programmer.ico").read_bytes()

    assert _ico_sizes(icon_payload) == {
        (16, 16),
        (20, 20),
        (24, 24),
        (32, 32),
        (40, 40),
        (48, 48),
        (64, 64),
        (128, 128),
        (256, 256),
    }
    for size in (16, 32, 48, 64):
        assert _png_size(
            web_asset_dir / f"vintage_programmer_{size}.png"
        ) == (size, size)
