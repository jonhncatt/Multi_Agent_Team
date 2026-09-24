from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from desktop.windows.assets.generate_icons import _remove_connected_background


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_icon_import_removes_connected_dark_and_light_canvases() -> None:
    for background in ((1, 1, 1), (255, 255, 255)):
        source = Image.new("RGB", (32, 32), background)
        ImageDraw.Draw(source).rectangle((8, 8, 23, 23), fill=(247, 91, 30))

        imported = _remove_connected_background(source)

        assert imported.getpixel((0, 0))[3] == 0
        assert imported.getpixel((16, 16))[3] == 255


def test_display_icon_is_optically_larger_than_the_imported_master() -> None:
    asset_dir = REPO_ROOT / "desktop" / "windows" / "assets"

    with Image.open(asset_dir / "validation_assistant_master.png") as master:
        master_bbox = master.convert("RGBA").getchannel("A").getbbox()
    with Image.open(asset_dir / "validation_assistant.png") as display_icon:
        display_bbox = display_icon.convert("RGBA").getchannel("A").getbbox()

    assert master_bbox is not None
    assert display_bbox is not None
    master_fill = (master_bbox[2] - master_bbox[0]) / 1024
    display_fill = (display_bbox[2] - display_bbox[0]) / 512
    assert master_fill < 0.86
    assert 0.90 <= display_fill <= 0.94


def test_small_taskbar_frames_match_web_icons_and_preserve_gradient() -> None:
    asset_dir = REPO_ROOT / "desktop" / "windows" / "assets"
    web_asset_dir = REPO_ROOT / "app" / "static" / "assets"

    with Image.open(asset_dir / "validation_assistant.ico") as icon:
        for size in (16, 32, 48, 64):
            embedded = icon.ico.getimage((size, size)).convert("RGBA")
            with Image.open(
                web_asset_dir / f"validation_assistant_{size}.png"
            ) as web_icon:
                assert ImageChops.difference(
                    embedded, web_icon.convert("RGBA")
                ).getbbox() is None

    # The title-bar/favicon rendition must retain the same warm gradient as the
    # full artwork instead of falling back to a flat orange tile.
    with Image.open(web_asset_dir / "validation_assistant_32.png") as small_icon:
        colors = small_icon.convert("RGBA").getcolors(maxcolors=32 * 32)
        assert colors is not None
        opaque_brand_colors = {
            (red, green, blue)
            for _, (red, green, blue, alpha) in colors
            if alpha >= 224 and not (red >= 240 and green >= 240 and blue >= 240)
        }
        assert len(opaque_brand_colors) > 300
        assert max(red for red, _, _ in opaque_brand_colors) - min(
            red for red, _, _ in opaque_brand_colors
        ) > 40
        assert max(green for _, green, _ in opaque_brand_colors) - min(
            green for _, green, _ in opaque_brand_colors
        ) > 80
        assert small_icon.getchannel("A").getextrema() == (0, 255)
