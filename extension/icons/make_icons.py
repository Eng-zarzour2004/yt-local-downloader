"""Generate simple placeholder PNG icons (no external deps)."""
import struct, zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent

def png_chunk(ctype: bytes, data: bytes) -> bytes:
    c = ctype + data
    return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

def solid_png(size: int, rgb: tuple) -> bytes:
    # 8-bit truecolor, solid bg with white rounded-ish play/download glyph approximation:
    # bg rose (#e11d48) with white down-arrow drawn programmatically
    w = h = size
    r0, g0, b0 = rgb
    px = bytearray()
    for y in range(h):
        px.append(0)  # filter byte
        for x in range(w):
            # white arrow shape: vertical bar + arrowhead, centered
            cx = w / 2
            bar_w = max(1, w // 8)
            head_h = h // 3
            in_bar = abs(x - cx) < bar_w and y < h * 0.55
            # triangle head
            rel = (y - h * 0.38) / (h * 0.3)
            half = max(0, (1 - abs(rel)) * w * 0.28) if 0 < rel < 2 else 0
            in_head = abs(x - cx) < half and h * 0.35 < y < h * 0.72
            if in_bar or in_head:
                px.extend((255, 255, 255))
            else:
                px.extend((r0, g0, b0))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = bytes(px)
    comp = zlib.compress(raw, 9)
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", ihdr)
            + png_chunk(b"IDAT", comp) + png_chunk(b"IEND", b""))

for size in (16, 48, 128):
    (OUT / f"icon{size}.png").write_bytes(solid_png(size, (225, 29, 72)))
    print("wrote", OUT / f"icon{size}.png")
