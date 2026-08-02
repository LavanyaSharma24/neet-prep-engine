"""One-off generator for placeholder PWA icons — stdlib only (zlib + struct),
no image library dependency. Produces solid-background + centered-circle
PNGs at the sizes web/public/manifest.json references.

These are placeholders so the app is installable tonight. Replace
web/public/icons/*.png with real branded artwork before a real launch.
"""
import struct
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = REPO_ROOT / "web" / "public" / "icons"

BACKGROUND = (11, 18, 32, 255)  # #0b1220
ACCENT = (47, 129, 247, 255)  # #2f81f7


def _write_png(path: Path, width: int, height: int, pixel_fn) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type: none
        for x in range(width):
            raw.extend(pixel_fn(x, y, width, height))

    compressed = zlib.compress(bytes(raw), 9)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    png = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")
    path.write_bytes(png)


def _circle_icon(radius_fraction: float):
    def pixel_fn(x: int, y: int, width: int, height: int):
        cx, cy = width / 2, height / 2
        r = radius_fraction * min(width, height) / 2
        dx, dy = x - cx + 0.5, y - cy + 0.5
        if dx * dx + dy * dy <= r * r:
            return ACCENT
        return BACKGROUND

    return pixel_fn


def build() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    # Regular icons: circle fills most of the square.
    _write_png(ICON_DIR / "icon-192.png", 192, 192, _circle_icon(0.7))
    _write_png(ICON_DIR / "icon-512.png", 512, 512, _circle_icon(0.7))
    # Maskable icons: keep content inside the ~80% safe zone.
    _write_png(ICON_DIR / "icon-maskable-192.png", 192, 192, _circle_icon(0.55))
    _write_png(ICON_DIR / "icon-maskable-512.png", 512, 512, _circle_icon(0.55))
    print(f"Wrote 4 placeholder icons to {ICON_DIR}")


if __name__ == "__main__":
    build()
