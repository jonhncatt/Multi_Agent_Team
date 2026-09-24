from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


CANVAS_SIZE = 1024
MASTER_FILENAME = "validation_assistant_master.png"
SHELL_ICON_FILENAME = "validation_assistant_shell.ico"
ICON_PIXEL_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
ICON_SIZES = tuple((size, size) for size in ICON_PIXEL_SIZES)
WEB_ICON_SIZES = (16, 32, 48, 64)


def _remove_connected_background(source: Image.Image) -> Image.Image:
    """Remove only the canvas color connected to an imported image's corners."""

    image = ImageOps.exif_transpose(source).convert("RGBA")
    probe = image.convert("RGB")
    # Keep the marker far from both dark and light corner colors. The previous
    # near-black marker made Pillow treat black backgrounds as already filled.
    marker = (0, 255, 0)
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
    # Preserve transparency supplied by generated or hand-authored source
    # artwork. Replacing it outright turns nearly-transparent edge pixels into
    # an opaque rectangular canvas.
    alpha = ImageChops.multiply(image.getchannel("A"), alpha)
    alpha = alpha.point(lambda value: 0 if value < 8 else value)
    image.putalpha(alpha)
    return image


def import_master(source_path: Path, asset_dir: Path) -> Image.Image:
    imported = _remove_connected_background(Image.open(source_path))
    # Preserve the source artwork's authored proportions. The approved VA
    # source already contains its intended outer margin, so adding a second
    # margin here would make the Windows icon look smaller than its peers.
    imported.thumbnail((CANVAS_SIZE, CANVAS_SIZE), Image.Resampling.LANCZOS)
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


def build_display_master(master: Image.Image) -> Image.Image:
    """Return the approved artwork without reconstructing its colors or shapes."""

    return master.copy()


def build_shell_master(display_master: Image.Image) -> Image.Image:
    """Firm the outer edge for Windows while preserving the approved artwork."""

    shape = display_master.getchannel("A").point(
        lambda value: 0
        if value < 8
        else 255
        if value >= 48
        else round((value - 8) * 255 / 40)
    )
    shell_master = display_master.copy()
    shell_master.putalpha(shape)
    return shell_master


def render_icon_frame(
    master: Image.Image,
    size: int,
) -> Image.Image:
    # Keep the original yellow-orange-red gradient at every native ICO size.
    # The previous two-color small rendition made Chrome's title-bar icon look
    # unrelated to the full application artwork.
    return master.resize((size, size), Image.Resampling.LANCZOS)


def write_derived_icons(master: Image.Image, asset_dir: Path) -> None:
    display_master = build_display_master(master)
    shell_master = build_shell_master(display_master)
    png = display_master.resize((512, 512), Image.Resampling.LANCZOS)
    png.save(asset_dir / "validation_assistant.png", optimize=True)
    icon_frames = [
        render_icon_frame(display_master, size)
        for size in ICON_PIXEL_SIZES
    ]
    icon_path = asset_dir / "validation_assistant.ico"
    icon_frames[-1].save(
        icon_path,
        format="ICO",
        append_images=icon_frames[:-1],
        sizes=ICON_SIZES,
    )
    shell_frames = [render_icon_frame(shell_master, size) for size in ICON_PIXEL_SIZES]
    # Keep a conservative DIB-encoded variant for the PE icon resource. Some
    # Windows Shell extensions fail while inspecting PNG-compressed frames
    # embedded in one-file executables, even though modern Windows supports
    # those frames in standalone .ico files.
    shell_frames[-1].save(
        asset_dir / SHELL_ICON_FILENAME,
        format="ICO",
        append_images=shell_frames[:-1],
        sizes=ICON_SIZES,
        bitmap_format="bmp",
    )

    web_asset_dir = asset_dir.parents[2] / "app" / "static" / "assets"
    web_asset_dir.mkdir(parents=True, exist_ok=True)
    png.save(web_asset_dir / "validation_assistant.png", optimize=True)
    for size in WEB_ICON_SIZES:
        render_icon_frame(display_master, size).save(
            web_asset_dir / f"validation_assistant_{size}.png",
            optimize=True,
        )
    (web_asset_dir / "validation_assistant.ico").write_bytes(icon_path.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate consistent VA desktop and web icons.")
    parser.add_argument("--source", type=Path, help="Import a new source image as the canonical icon")
    args = parser.parse_args()

    asset_dir = Path(__file__).resolve().parent
    master = import_master(args.source.expanduser().resolve(), asset_dir) if args.source else load_master(asset_dir)
    write_derived_icons(master, asset_dir)


if __name__ == "__main__":
    main()
