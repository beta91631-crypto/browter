import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from browsercmd.config import DEFAULT_SETTINGS, PixelSettings, load_settings, save_settings, validate_settings
from browsercmd.pixel import render_file, render_image, self_test


class PixelTests(unittest.TestCase):
    def test_settings_are_clamped_and_persisted(self):
        settings = validate_settings(
            {"pixel_size": 99, "palette": 17, "dither": "bad", "style": "bad", "images": "bad"}
        )
        self.assertEqual(settings.pixel_size, 6)
        self.assertEqual(settings.palette, 16)
        self.assertEqual(settings.dither, DEFAULT_SETTINGS.dither)
        self.assertEqual(settings.style, DEFAULT_SETTINGS.style)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            save_settings(settings, path)
            self.assertEqual(load_settings(path), settings)

    def test_render_is_deterministic_and_uses_half_block_truecolor(self):
        image = Image.new("RGB", (8, 8), (255, 0, 0))
        settings = PixelSettings(pixel_size=1, palette=4, dither="off")
        first = render_image(image, settings, width=4, height=4)
        second = render_image(image, settings, width=4, height=4)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertTrue(all(line == "\x1b[38;2;255;0;0m\x1b[48;2;255;0;0m▀" * 4 + "\x1b[0m" for line in first))

    def test_styles_palettes_and_pixel_sizes_change_output(self):
        y_coords, x_coords = np.indices((32, 32))
        array = np.stack((x_coords * 8, y_coords * 8, (x_coords * 13 + y_coords * 7) % 256), axis=2).astype(np.uint8)
        image = Image.fromarray(array)
        base = render_image(image, PixelSettings(pixel_size=1, palette=64, dither="off"), 16, 8)
        variants = (
            render_image(image, PixelSettings(pixel_size=4, palette=64, dither="off"), 16, 8),
            render_image(image, PixelSettings(pixel_size=1, palette=8, dither="off"), 16, 8),
            render_image(image, PixelSettings(pixel_size=1, palette=64, dither="off", style="gameboy"), 16, 8),
            render_image(image, PixelSettings(pixel_size=1, palette=64, dither="off", style="mono"), 16, 8),
            render_image(image, PixelSettings(pixel_size=1, palette=64, dither="off", style="retro"), 16, 8),
        )
        for variant in variants:
            self.assertNotEqual(base, variant)

    def test_color_fallbacks_and_input_limits(self):
        image = Image.new("RGB", (4, 4), (40, 90, 160))
        for mode in ("256", "16"):
            lines = render_image(image, PixelSettings(pixel_size=1), 4, 2, mode)
            self.assertTrue(all("\x1b[" in line and "▀" in line for line in lines))
        with self.assertRaisesRegex(ValueError, "positive"):
            render_image(Image.new("RGB", (2, 2)), width=0)

    def test_file_render_and_image_pipeline_self_test(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.png"
            Image.new("RGB", (12, 8), (20, 140, 220)).save(path)
            lines = render_file(path, PixelSettings(), 12, 6)
            self.assertTrue(lines)
        self.assertIn("VERIFIED", self_test())

    def test_standalone_command_renders_and_logs_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "command.png"
            Image.new("RGB", (8, 8), (12, 34, 56)).save(image_path)
            environment = os.environ.copy()
            environment["BROWSERCMD_LOGS_DIR"] = directory
            result = subprocess.run(
                [sys.executable, "-m", "browsercmd.pixel", str(image_path), "--width", "4", "--height", "2"],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("▀", result.stdout)
            session_log = next(Path(directory).glob("session-*.txt")).read_text(encoding="utf-8")
            self.assertIn("Image rendered:", session_log)
            self.assertIn("elapsed_ms=", session_log)


if __name__ == "__main__":
    unittest.main()