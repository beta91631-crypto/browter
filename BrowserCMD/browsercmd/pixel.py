"""Deterministic Pillow/NumPy image-to-terminal pixel-art renderer."""

from __future__ import annotations

import argparse
import hashlib
import logging
import time
import warnings
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .config import PixelSettings, load_settings, validate_settings
from .logging_setup import setup_logging

MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_BYTES = 20 * 1024 * 1024
BAYER_4 = np.array(
    [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
    dtype=np.float32,
)
GAMEBOY_PALETTE = ((232, 248, 208), (136, 192, 112), (52, 104, 86), (8, 24, 32))
RETRO_PALETTE = (
    (0, 0, 0), (32, 32, 32), (64, 64, 64), (96, 96, 96),
    (128, 128, 128), (160, 160, 160), (192, 192, 192), (224, 224, 224),
    (255, 255, 255), (0, 48, 88), (0, 104, 136), (0, 160, 160),
    (24, 120, 64), (120, 168, 40), (200, 144, 40), (192, 64, 56),
)
ANSI16 = (
    (0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0),
    (0, 0, 128), (128, 0, 128), (0, 128, 128), (192, 192, 192),
    (128, 128, 128), (255, 0, 0), (0, 255, 0), (255, 255, 0),
    (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
)


def _nearest_color(color: tuple[int, int, int], palette: tuple[tuple[int, int, int], ...]) -> int:
    red, green, blue = color
    return min(
        range(len(palette)),
        key=lambda index: (
            (red - palette[index][0]) ** 2
            + (green - palette[index][1]) ** 2
            + (blue - palette[index][2]) ** 2
        ),
    )


def _xterm_palette() -> tuple[tuple[int, int, int], ...]:
    base = ANSI16
    levels = (0, 95, 135, 175, 215, 255)
    cube = tuple((red, green, blue) for red in levels for green in levels for blue in levels)
    gray = tuple((value, value, value) for value in range(8, 239, 10))
    return (*base, *cube, *gray)


XTERM_PALETTE = _xterm_palette()


def _nearest_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return image.resize(size, Image.Resampling.NEAREST)


def _quantize(image: Image.Image, settings: PixelSettings) -> Image.Image:
    if settings.style in ("gameboy", "retro"):
        palette_image = Image.new("P", (1, 1))
        palette = GAMEBOY_PALETTE if settings.style == "gameboy" else RETRO_PALETTE
        flat_palette = [channel for color in palette for channel in color]
        flat_palette.extend([0] * (768 - len(flat_palette)))
        palette_image.putpalette(flat_palette)
        return image.quantize(palette=palette_image, dither=Image.Dither.NONE)
    if settings.style == "mono":
        image = ImageOps.grayscale(image).convert("RGB")

    colors = 16 if settings.style == "retro" else settings.palette
    if settings.dither == "ordered":
        rgb = np.asarray(image, dtype=np.float32).copy()
        height, width = rgb.shape[:2]
        threshold = (BAYER_4[np.arange(height)[:, None] % 4, np.arange(width)[None, :] % 4] / 16 - 0.5)
        magnitude = 255 / max(2, round(colors ** (1 / 3)))
        rgb = np.clip(rgb + threshold[..., None] * magnitude, 0, 255).astype(np.uint8)
        image = Image.fromarray(rgb, mode="RGB")
    dither = Image.Dither.FLOYDSTEINBERG if settings.dither == "floyd" else Image.Dither.NONE
    return image.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=dither)


def _terminal_color(color: tuple[int, int, int], mode: str) -> tuple[int, str]:
    if mode == "truecolor":
        red, green, blue = color
        return -1, f"{red};{green};{blue}"
    palette = XTERM_PALETTE if mode == "256" else ANSI16
    index = _nearest_color(color, palette)
    if mode == "256":
        return index, str(index)
    return index, str(index)


def _color_escape(color: tuple[int, int, int], mode: str, foreground: bool) -> str:
    base = 38 if foreground else 48
    if mode == "truecolor":
        red, green, blue = color
        return f"\x1b[{base};2;{red};{green};{blue}m"
    index, _ = _terminal_color(color, mode)
    if mode == "256":
        return f"\x1b[{base};5;{index}m"
    code = 30 if foreground else 40
    return f"\x1b[{code + index}m" if index < 8 else f"\x1b[{(90 if foreground else 100) + index - 8}m"


def _paint(pair: np.ndarray, mode: str) -> str:
    top = tuple(int(channel) for channel in pair[0])
    bottom = tuple(int(channel) for channel in pair[1])
    return f"{_color_escape(top, mode, True)}{_color_escape(bottom, mode, False)}▀"


def _dimensions(image: Image.Image, width: int, height: int, pixel_size: int) -> tuple[int, int]:
    scale = min(width / image.width, (height * 2) / image.height)
    target_width = max(1, int(image.width * scale))
    target_height = max(1, int(image.height * scale))
    block_width = max(1, target_width // pixel_size)
    block_height = max(1, target_height // pixel_size)
    return min(width, block_width * pixel_size), min(height * 2, block_height * pixel_size)


def render_image(
    image: Image.Image,
    settings: PixelSettings | None = None,
    width: int = 40,
    height: int = 16,
    color_mode: str = "truecolor",
) -> list[str]:
    """Return ANSI half-block lines sized to a terminal cell rectangle."""
    if width < 1 or height < 1:
        raise ValueError("Terminal image dimensions must be positive")
    if color_mode not in ("truecolor", "256", "16"):
        raise ValueError("color_mode must be truecolor, 256, or 16")
    settings = validate_settings({} if settings is None else settings.__dict__)
    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise ValueError("Image exceeds the 20-megapixel limit")
    source = image.convert("RGB")
    block_width, block_height = _dimensions(source, width, height, settings.pixel_size)
    coarse_width = max(1, block_width // settings.pixel_size)
    coarse_height = max(1, block_height // settings.pixel_size)
    coarse = _nearest_resize(source, (coarse_width, coarse_height))
    quantized = _quantize(coarse, settings).convert("RGB")
    enlarged = _nearest_resize(quantized, (block_width, block_height))
    pixels = np.asarray(enlarged, dtype=np.uint8)
    if block_height % 2:
        pixels = np.concatenate((pixels, np.zeros((1, block_width, 3), dtype=np.uint8)), axis=0)

    lines: list[str] = []
    for row in range(0, pixels.shape[0], 2):
        line = "".join(_paint(pixels[row : row + 2, column], color_mode) for column in range(block_width))
        lines.append(line + "\x1b[0m")
    return lines


def render_file(
    path: Path | str,
    settings: PixelSettings | None = None,
    width: int = 40,
    height: int = 16,
    color_mode: str = "truecolor",
) -> list[str]:
    image_path = Path(path)
    if image_path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("Image file exceeds the 20 MiB limit")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(image_path) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("Image exceeds the 20-megapixel limit")
            return render_image(image, settings, width, height, color_mode)


def self_test() -> str:
    started = time.perf_counter()
    gradient = np.zeros((48, 64, 3), dtype=np.uint8)
    gradient[:, :, 0] = np.arange(64, dtype=np.uint8)[None, :] * 4
    gradient[:, :, 1] = np.arange(48, dtype=np.uint8)[:, None] * 5
    gradient[:, :, 2] = 120
    lines = render_image(Image.fromarray(gradient), PixelSettings(), width=32, height=16)
    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()[:12]
    elapsed_ms = (time.perf_counter() - started) * 1000
    return f"VERIFIED {len(lines)} rows, {sum(len(line) for line in lines)} chars, {elapsed_ms:.2f} ms, sha256={digest}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render an image as terminal pixel art")
    parser.add_argument("image", type=Path)
    parser.add_argument("--width", type=int, default=40)
    parser.add_argument("--height", type=int, default=16)
    parser.add_argument("--color-mode", choices=("truecolor", "256", "16"), default="truecolor")
    parser.add_argument("--pixel-size", type=int)
    parser.add_argument("--palette", type=int)
    parser.add_argument("--dither", choices=("off", "ordered", "floyd"))
    parser.add_argument("--style", choices=("clean", "retro", "gameboy", "mono"))
    args = parser.parse_args()
    settings = load_settings()
    overrides = settings.__dict__.copy()
    for key in ("pixel_size", "palette", "dither", "style"):
        value = getattr(args, key)
        if value is not None:
            overrides[key] = value
    settings = validate_settings(overrides)
    logger, log_path = setup_logging(
        config={"pixel_size": settings.pixel_size, "palette": settings.palette, "style": settings.style}
    )
    started = time.perf_counter()
    try:
        lines = render_file(args.image, settings, args.width, args.height, args.color_mode)
    except Exception as error:
        logger.exception("Image render failed: %s", args.image)
        print(f"Image render failed: {type(error).__name__}. Log saved: {log_path}")
        return 1
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "Image rendered: path=%s rows=%d elapsed_ms=%.2f style=%s palette=%d pixel_size=%d",
        args.image,
        len(lines),
        elapsed_ms,
        settings.style,
        settings.palette,
        settings.pixel_size,
    )
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())