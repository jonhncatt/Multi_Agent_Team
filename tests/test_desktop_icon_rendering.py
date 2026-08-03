from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_small_taskbar_frames_match_web_icons_and_remain_visually_flat() -> None:
    asset_dir = REPO_ROOT / "desktop" / "windows" / "assets"
    web_asset_dir = REPO_ROOT / "app" / "static" / "assets"

    with Image.open(asset_dir / "vintage_programmer.ico") as icon:
        for size in (16, 32, 48, 64):
            embedded = icon.ico.getimage((size, size)).convert("RGBA")
            with Image.open(
                web_asset_dir / f"vintage_programmer_{size}.png"
            ) as web_icon:
                assert ImageChops.difference(
                    embedded, web_icon.convert("RGBA")
                ).getbbox() is None

    # The taskbar rendition intentionally removes the large artwork's gradient,
    # shadow, and glow. Antialiasing still introduces intermediate edge colors.
    with Image.open(web_asset_dir / "vintage_programmer_32.png") as small_icon:
        colors = small_icon.convert("RGBA").getcolors(maxcolors=32 * 32)
        assert colors is not None
        assert len(colors) < 300
        assert small_icon.getchannel("A").getextrema() == (0, 255)
