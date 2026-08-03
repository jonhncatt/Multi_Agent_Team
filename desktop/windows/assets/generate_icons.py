from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps


CANVAS_SIZE = 1024
MASTER_FILENAME = "vintage_programmer_master.png"
ICON_SIZES = tuple((size, size) for size in (16, 24, 32, 48, 64, 128, 256))


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


def write_derived_icons(master: Image.Image, asset_dir: Path) -> None:
    png = master.resize((512, 512), Image.Resampling.LANCZOS)
    png.save(asset_dir / "vintage_programmer.png", optimize=True)
    master.save(asset_dir / "vintage_programmer.ico", format="ICO", sizes=ICON_SIZES)

    web_asset_dir = asset_dir.parents[2] / "app" / "static" / "assets"
    web_asset_dir.mkdir(parents=True, exist_ok=True)
    png.save(web_asset_dir / "vintage_programmer.png", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate consistent VP desktop and web icons.")
    parser.add_argument("--source", type=Path, help="Import a new source image as the canonical icon")
    args = parser.parse_args()

    asset_dir = Path(__file__).resolve().parent
    master = import_master(args.source.expanduser().resolve(), asset_dir) if args.source else load_master(asset_dir)
    write_derived_icons(master, asset_dir)


if __name__ == "__main__":
    main()
