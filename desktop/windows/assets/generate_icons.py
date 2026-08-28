from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


CANVAS_SIZE = 1024
MASTER_FILENAME = "vintage_programmer_master.png"
SHELL_ICON_FILENAME = "vintage_programmer_shell.ico"
ICON_PIXEL_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
ICON_SIZES = tuple((size, size) for size in ICON_PIXEL_SIZES)
WEB_ICON_SIZES = (16, 32, 48, 64)
TASKBAR_MAX_SIZE = 64
TASKBAR_ORANGE = (247, 91, 30)
TASKBAR_MARK = (255, 250, 244)


def _remove_connected_light_background(source: Image.Image) -> Image.Image:
    """Remove only the light canvas connected to an imported image's corners."""

    image = ImageOps.exif_transpose(source).convert("RGBA")
    probe = image.convert("RGB")
    marker = (1, 2, 3)
    corners = (
        (0, 0),
        (image.width - 1, 0),
        (0, image.height - 1),
        (image.width - 1, image.height - 1),
    )
    for seed in corners:
        ImageDraw.floodfill(probe, seed, marker, thresh=48)

    probe_pixels = probe.load()
    alpha = Image.new("L", image.size, 255)
    alpha_pixels = alpha.load()
    for y in range(image.height):
        for x in range(image.width):
            if probe_pixels[x, y] == marker:
                alpha_pixels[x, y] = 0

    # Pull the mask inward by two source pixels to remove the original white
    # matte, then retain a soft antialiased edge on transparent backgrounds.
    alpha = alpha.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(0.7))
    image.putalpha(alpha)
    return image


def import_master(source_path: Path, asset_dir: Path) -> Image.Image:
    imported = _remove_connected_light_background(Image.open(source_path))
    imported.thumbnail((960, 960), Image.Resampling.LANCZOS)
    master = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    position = ((CANVAS_SIZE - imported.width) // 2, (CANVAS_SIZE - imported.height) // 2)
    master.alpha_composite(imported, position)
    master.save(asset_dir / MASTER_FILENAME, optimize=True)
    return master


def load_master(asset_dir: Path) -> Image.Image:
    master_path = asset_dir / MASTER_FILENAME
    if not master_path.is_file():
        raise SystemExit(f"Missing master icon: {master_path}. Pass --source once to import it.")
    return Image.open(master_path).convert("RGBA")


def build_taskbar_master(master: Image.Image) -> Image.Image:
    """Flatten soft artwork so the VP mark stays legible at taskbar sizes."""

    # The source artwork intentionally has gradients, glow, and a soft shadow.
    # Those details look good at large sizes but turn into a fuzzy fringe when
    # Chrome asks Windows for a 16-64 px favicon. Preserve the original shape
    # while reducing the small rendition to two high-contrast brand colors.
    shape = master.getchannel("A").point(
        lambda value: 0
        if value < 24
        else 255
        if value > 232
        else round((value - 24) * 255 / 208)
    )
    mark = master.getchannel("B").point(
        lambda value: 0
        if value < 96
        else 255
        if value > 210
        else round((value - 96) * 255 / 114)
    )
    mark = ImageChops.multiply(mark, shape)

    taskbar_master = Image.new("RGBA", master.size, (*TASKBAR_ORANGE, 0))
    taskbar_master.putalpha(shape)
    foreground = Image.new("RGBA", master.size, (*TASKBAR_MARK, 0))
    foreground.putalpha(mark)
    taskbar_master.alpha_composite(foreground)
    return taskbar_master


def render_icon_frame(
    master: Image.Image,
    size: int,
    *,
    taskbar_master: Image.Image | None = None,
) -> Image.Image:
    if size <= TASKBAR_MAX_SIZE:
        source = taskbar_master or build_taskbar_master(master)
    else:
        source = master
    return source.resize((size, size), Image.Resampling.LANCZOS)


def write_derived_icons(master: Image.Image, asset_dir: Path) -> None:
    png = master.resize((512, 512), Image.Resampling.LANCZOS)
    png.save(asset_dir / "vintage_programmer.png", optimize=True)
    taskbar_master = build_taskbar_master(master)
    icon_frames = [
        render_icon_frame(master, size, taskbar_master=taskbar_master)
        for size in ICON_PIXEL_SIZES
    ]
    icon_path = asset_dir / "vintage_programmer.ico"
    icon_frames[-1].save(
        icon_path,
        format="ICO",
        append_images=icon_frames[:-1],
        sizes=ICON_SIZES,
    )
    # Keep a conservative DIB-encoded variant for the PE icon resource. Some
    # Windows Shell extensions fail while inspecting PNG-compressed frames
    # embedded in one-file executables, even though modern Windows supports
    # those frames in standalone .ico files.
    icon_frames[-1].save(
        asset_dir / SHELL_ICON_FILENAME,
        format="ICO",
        append_images=icon_frames[:-1],
        sizes=ICON_SIZES,
        bitmap_format="bmp",
    )

    web_asset_dir = asset_dir.parents[2] / "app" / "static" / "assets"
    web_asset_dir.mkdir(parents=True, exist_ok=True)
    png.save(web_asset_dir / "vintage_programmer.png", optimize=True)
    for size in WEB_ICON_SIZES:
        render_icon_frame(master, size, taskbar_master=taskbar_master).save(
            web_asset_dir / f"vintage_programmer_{size}.png",
            optimize=True,
        )
    (web_asset_dir / "vintage_programmer.ico").write_bytes(icon_path.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate consistent VP desktop and web icons.")
    parser.add_argument("--source", type=Path, help="Import a new source image as the canonical icon")
    args = parser.parse_args()

    asset_dir = Path(__file__).resolve().parent
    master = import_master(args.source.expanduser().resolve(), asset_dir) if args.source else load_master(asset_dir)
    write_derived_icons(master, asset_dir)


if __name__ == "__main__":
    main()
