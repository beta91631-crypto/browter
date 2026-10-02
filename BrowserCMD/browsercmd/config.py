"""Validated BrowserCMD settings and JSON persistence."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PALETTE_VALUES = (4, 8, 16, 32, 64)
DITHER_VALUES = ("off", "ordered", "floyd")
STYLE_VALUES = ("clean", "retro", "gameboy", "mono")
IMAGE_SCALE_VALUES = ("small", "medium", "large", "fit-width")
IMAGE_VALUES = ("on", "off", "thumbnails-only")
BACKEND_VALUES = ("halfblock", "chafa", "sixel")


@dataclass(frozen=True)
class PixelSettings:
    pixel_size: int = 2
    palette: int = 32
    dither: str = "ordered"
    style: str = "clean"
    image_scale: str = "medium"
    images: str = "on"
    backend: str = "halfblock"


DEFAULT_SETTINGS = PixelSettings()
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def validate_settings(values: dict[str, Any] | None) -> PixelSettings:
    values = values if isinstance(values, dict) else {}
    try:
        requested_size = int(values.get("pixel_size", DEFAULT_SETTINGS.pixel_size))
    except (TypeError, ValueError, OverflowError):
        requested_size = DEFAULT_SETTINGS.pixel_size
    pixel_size = min(6, max(1, requested_size))

    try:
        requested_palette = int(values.get("palette", DEFAULT_SETTINGS.palette))
    except (TypeError, ValueError, OverflowError):
        requested_palette = DEFAULT_SETTINGS.palette
    palette = min(PALETTE_VALUES, key=lambda allowed: (abs(allowed - requested_palette), allowed))

    return PixelSettings(
        pixel_size=pixel_size,
        palette=palette,
        dither=_choice(values.get("dither"), DITHER_VALUES, DEFAULT_SETTINGS.dither),
        style=_choice(values.get("style"), STYLE_VALUES, DEFAULT_SETTINGS.style),
        image_scale=_choice(values.get("image_scale"), IMAGE_SCALE_VALUES, DEFAULT_SETTINGS.image_scale),
        images=_choice(values.get("images"), IMAGE_VALUES, DEFAULT_SETTINGS.images),
        backend=_choice(values.get("backend"), BACKEND_VALUES, DEFAULT_SETTINGS.backend),
    )


def load_settings(path: Path | str = CONFIG_PATH) -> PixelSettings:
    config_path = Path(path)
    try:
        values = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DEFAULT_SETTINGS
    except (OSError, json.JSONDecodeError):
        return DEFAULT_SETTINGS
    return validate_settings(values)


def save_settings(settings: PixelSettings, path: Path | str = CONFIG_PATH) -> None:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(validate_settings(asdict(settings))), indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f"{config_path.name}.", dir=config_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, config_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise