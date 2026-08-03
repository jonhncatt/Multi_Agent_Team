from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops


REPO_ROOT = Path(__file__).resolve().parents[1]


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


def test_windows_icon_uses_exact_flat_frames_for_small_taskbar_sizes() -> None:
    asset_dir = REPO_ROOT / "desktop" / "windows" / "assets"
    web_asset_dir = REPO_ROOT / "app" / "static" / "assets"

    with Image.open(asset_dir / "vintage_programmer.ico") as icon:
        assert icon.ico.sizes() == {
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
            embedded = icon.ico.getimage((size, size)).convert("RGBA")
            with Image.open(
                web_asset_dir / f"vintage_programmer_{size}.png"
            ) as web_icon:
                assert ImageChops.difference(
                    embedded, web_icon.convert("RGBA")
                ).getbbox() is None

    # A flat taskbar frame should have substantially less color variation than
    # the full-size gradient artwork, while retaining transparency and detail.
    with Image.open(web_asset_dir / "vintage_programmer_32.png") as small_icon:
        colors = small_icon.convert("RGBA").getcolors(maxcolors=32 * 32)
        assert colors is not None
        assert len(colors) < 300
        alpha_extrema = small_icon.getchannel("A").getextrema()
        assert alpha_extrema == (0, 255)
