"""Generate the simple deterministic Windows icon used by the installer and tray."""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


def png_rgba(size: int) -> bytes:
    rows = bytearray()
    center = (size - 1) / 2
    for y in range(size):
        rows.append(0)
        for x in range(size):
            dx, dy = x - center, y - center
            radius = math.sqrt(dx * dx + dy * dy) / size
            shade = max(0, min(255, int(24 + (1 - radius * 1.5) * 24)))
            pixel = (shade, shade + 10, min(255, shade + 34), 255)
            # Four-point light mark centered in the rounded desktop tile.
            nx, ny = abs(dx) / size, abs(dy) / size
            horizontal = ny < 0.055 and nx < 0.29
            vertical = nx < 0.055 and ny < 0.29
            diagonal = abs(nx - ny) < 0.04 and nx < 0.17
            inner = math.sqrt(dx * dx + dy * dy) < size * 0.115
            if horizontal or vertical or diagonal or inner:
                pixel = (205, 224, 255, 255) if inner else (113, 171, 255, 255)
            rows.extend(pixel)

    def chunk(name: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "src-tauri" / "icons"
    target.mkdir(parents=True, exist_ok=True)
    png = png_rgba(256)
    (target / "icon.png").write_bytes(png)
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    (target / "icon.ico").write_bytes(header + entry + png)


if __name__ == "__main__":
    main()
