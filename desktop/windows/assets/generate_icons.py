from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


CANVAS_SIZE = 1024
ICON_SIZES = tuple((size, size) for size in (16, 24, 32, 48, 64, 128, 256))
ORANGE_TOP = (255, 135, 64, 255)
ORANGE_BOTTOM = (243, 112, 33, 255)
WHITE = (255, 255, 255, 255)


def _gradient_background() -> Image.Image:
    gradient = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE))
    pixels = gradient.load()
    for y in range(CANVAS_SIZE):
        ratio = y / max(1, CANVAS_SIZE - 1)
        color = tuple(
            round(top + ((bottom - top) * ratio))
            for top, bottom in zip(ORANGE_TOP, ORANGE_BOTTOM)
        )
        for x in range(CANVAS_SIZE):
            pixels[x, y] = color

    mask = Image.new("L", (CANVAS_SIZE, CANVAS_SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((32, 32, 992, 992), radius=224, fill=255)
    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    canvas.alpha_composite(Image.composite(gradient, canvas, mask))
    return canvas


def _draw_round_path(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]], width: int) -> None:
    draw.line(points, fill=WHITE, width=width, joint="curve")
    radius = width // 2
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=WHITE)


def _cubic_points(
    start: tuple[int, int],
    control_1: tuple[int, int],
    control_2: tuple[int, int],
    end: tuple[int, int],
    *,
    steps: int = 24,
) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    for index in range(steps + 1):
        t = index / steps
        inverse = 1 - t
        x = (
            (inverse**3 * start[0])
            + (3 * inverse * inverse * t * control_1[0])
            + (3 * inverse * t * t * control_2[0])
            + (t**3 * end[0])
        )
        y = (
            (inverse**3 * start[1])
            + (3 * inverse * inverse * t * control_1[1])
            + (3 * inverse * t * t * control_2[1])
            + (t**3 * end[1])
        )
        points.append((round(x), round(y)))
    return points


def render_master() -> Image.Image:
    image = _gradient_background()
    draw = ImageDraw.Draw(image)
    stroke = 88
    _draw_round_path(draw, [(236, 340), (396, 688), (556, 340)], stroke)

    p_path = [(624, 688), (624, 340), (732, 340)]
    p_path.extend(_cubic_points((732, 340), (876, 340), (876, 520), (732, 520))[1:])
    p_path.append((624, 520))
    _draw_round_path(draw, p_path, stroke)
    return image


def main() -> None:
    asset_dir = Path(__file__).resolve().parent
    master = render_master()
    png_path = asset_dir / "vintage_programmer.png"
    ico_path = asset_dir / "vintage_programmer.ico"
    master.resize((512, 512), Image.Resampling.LANCZOS).save(png_path, optimize=True)
    master.save(ico_path, format="ICO", sizes=ICON_SIZES)


if __name__ == "__main__":
    main()
