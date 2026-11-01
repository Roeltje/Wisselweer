"""Kleine afbeeldingsbestanden, met de hand opgebouwd (geen Pillow): alleen de structuur klopt.

De bestanden zijn geen echte afbeeldingen die een viewer kan tonen; de fotomodule leest alleen
de containerstructuur (segmenten/chunks) en laat de beelddata ongemoeid.
"""

from __future__ import annotations

import struct
import zlib

GPS_TEXT = b"GPS 52.0907 N 5.1214 E"
EXIF_PAYLOAD = b"Exif\x00\x00II*\x00" + GPS_TEXT
SCAN_DATA = b"\x12\x34\xff\x00\x56\xff\xd0\x78"  # met een gestuffde 0xFF en een restart-marker


def jpeg_segment(marker: int, payload: bytes) -> bytes:
    return b"\xff" + bytes([marker]) + (len(payload) + 2).to_bytes(2, "big") + payload


def make_jpeg(*before_scan: bytes, scan: bytes = SCAN_DATA, trailer: bytes = b"") -> bytes:
    """SOI, JFIF, extra segmenten, DQT, SOF0, SOS, scandata, EOI en eventueel data erna."""
    return (
        b"\xff\xd8"
        + jpeg_segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
        + b"".join(before_scan)
        + jpeg_segment(0xDB, b"\x00" + bytes(64))
        + jpeg_segment(0xC0, b"\x08\x00\x08\x00\x08\x01\x01\x11\x00")
        + jpeg_segment(0xDA, b"\x01\x01\x00\x00\x3f\x00")
        + scan
        + b"\xff\xd9"
        + trailer
    )


def make_jpeg_with_exif() -> bytes:
    return make_jpeg(jpeg_segment(0xE1, EXIF_PAYLOAD))


def png_chunk(kind: bytes, payload: bytes = b"") -> bytes:
    crc = zlib.crc32(kind + payload)
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def make_png(*before_idat: bytes, trailer: bytes = b"") -> bytes:
    ihdr = png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = png_chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    return b"\x89PNG\r\n\x1a\n" + ihdr + b"".join(before_idat) + idat + png_chunk(b"IEND") + trailer


def make_png_with_text() -> bytes:
    return make_png(png_chunk(b"tEXt", b"Comment\x00" + GPS_TEXT))


def riff_chunk(kind: bytes, payload: bytes) -> bytes:
    pad = b"\x00" if len(payload) % 2 else b""
    return kind + struct.pack("<I", len(payload)) + payload + pad


def riff_webp(*chunks: bytes) -> bytes:
    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def vp8x(flags: int) -> bytes:
    return riff_chunk(b"VP8X", bytes([flags]) + b"\x00\x00\x00" + b"\x07\x00\x00" + b"\x07\x00\x00")


# Vlaggen in de VP8X-chunk
VP8X_ICC, VP8X_ALPHA, VP8X_EXIF, VP8X_XMP = 0x20, 0x10, 0x08, 0x04
# Oneven lengte, zodat de aanvulbyte ook getest wordt.
FAKE_BITSTREAM = b"\x01\x02\x03\x04\x05"


def make_webp_with_exif() -> bytes:
    flags = VP8X_ICC | VP8X_ALPHA | VP8X_EXIF | VP8X_XMP
    return riff_webp(
        vp8x(flags),
        riff_chunk(b"ICCP", b"icc!"),
        riff_chunk(b"VP8 ", FAKE_BITSTREAM),
        riff_chunk(b"EXIF", b"Exif\x00\x00II*\x00" + GPS_TEXT + b"!"),
        riff_chunk(b"XMP ", b"<x:xmpmeta>" + GPS_TEXT + b"</x:xmpmeta>"),
    )
