#!/usr/bin/env python3
"""Turn a screenshot of the app into the app icons.

    python tools/make_icon.py assets/icon-source.png

Writes assets/icon.png (1024x1024, the window/Dock icon), assets/GeniusControl.icns
(macOS .app) and assets/GeniusControl.ico (Windows .exe).
Needs Pillow (pip install pillow); the .icns also needs macOS iconutil.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
CANVAS = 1024
BODY = 880  # tallest side of the artwork inside the 1024 canvas (Apple grid ~ 824-880)


def rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def make_master(src: Path) -> Image.Image:
    shot = Image.open(src).convert("RGBA")
    # Trim a couple of pixels of desktop around the window edge, then round the corners.
    shot = shot.crop((3, 3, shot.width - 3, shot.height - 3))
    shot = rounded(shot, radius=max(12, shot.width // 24))
    scale = BODY / max(shot.size)
    shot = shot.resize((round(shot.width * scale), round(shot.height * scale)), Image.LANCZOS)

    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    x = (CANVAS - shot.width) // 2
    y = (CANVAS - shot.height) // 2 - 8
    shadow = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    shadow_mask = Image.new("L", (CANVAS, CANVAS), 0)
    shadow_mask.paste(shot.getchannel("A"), (x, y + 14))
    shadow.putalpha(shadow_mask.point(lambda a: a * 0.45).filter(ImageFilter.GaussianBlur(18)))
    canvas = Image.alpha_composite(canvas, shadow)
    canvas.alpha_composite(shot, (x, y))
    return canvas


def write_icns(master: Image.Image, dest: Path):
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "GeniusControl.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            master.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
            master.resize((size * 2, size * 2), Image.LANCZOS).save(
                iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest)], check=True)


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ASSETS / "icon-source.png"
    ASSETS.mkdir(exist_ok=True)
    if src.resolve() != (ASSETS / "icon-source.png").resolve():
        shutil.copyfile(src, ASSETS / "icon-source.png")
    master = make_master(src)
    master.save(ASSETS / "icon.png")
    master.save(ASSETS / "GeniusControl.ico",
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    if shutil.which("iconutil"):
        write_icns(master, ASSETS / "GeniusControl.icns")
    print(f"Wrote icon.png, GeniusControl.ico and GeniusControl.icns in {ASSETS}")


if __name__ == "__main__":
    main()
