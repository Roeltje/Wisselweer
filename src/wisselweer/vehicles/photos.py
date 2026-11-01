"""Voertuigfoto's: type bepalen op magic bytes, metadata (EXIF/GPS) strippen en veilig opslaan.

Zonder Pillow: JPEG, PNG en WebP zijn containers van segmenten/chunks, dus metadata is te
verwijderen zonder de beelddata aan te raken. Bewaard wordt nooit wat de gebruiker uploadt, maar de
opgeschoonde bytes onder een willekeurige naam; een door de gebruiker aangeleverde bestandsnaam
wordt nergens gebruikt.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import zlib
from pathlib import Path

log = logging.getLogger("wisselweer.photos")

MAX_BYTES = 2 * 1024 * 1024

# De opgeslagen naam is `<32 hex>.<extensie>`: geen scheidingstekens, dus geen path traversal.
PHOTO_NAME_RE = re.compile(r"[0-9a-f]{32}\.(?:webp|jpg|png)")
CONTENT_TYPES = {".webp": "image/webp", ".jpg": "image/jpeg", ".png": "image/png"}


class PhotoError(ValueError):
    """Foto geweigerd. `code` is het achtervoegsel van de i18n-sleutel `photo.error.<code>`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _corrupt() -> PhotoError:
    return PhotoError("corrupt")


# --------------------------------------------------------------------------- JPEG

# APP1-APP13, APP15 en COM; APP0 (JFIF) en APP14 (Adobe, kleurruimte) blijven staan.
_JPEG_DROP = frozenset([*range(0xE1, 0xEE), 0xEF, 0xFE])
# SOF0-SOF15, behalve DHT (C4), JPG (C8) en DAC (CC).
_JPEG_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def _jpeg_scan_end(data: bytes, pos: int) -> int:
    """Positie van de eerste marker na de entropiegecodeerde data die op `pos` begint."""
    n = len(data)
    while True:
        pos = data.find(b"\xff", pos)
        if pos < 0 or pos + 1 >= n:
            raise _corrupt()
        nxt = data[pos + 1]
        if nxt == 0xFF:  # vulbyte
            pos += 1
        elif nxt == 0x00 or 0xD0 <= nxt <= 0xD7:  # gestuffde 0xFF of restart-marker
            pos += 2
        else:
            return pos


def _strip_jpeg(data: bytes) -> bytes:
    """Verwijdert metadata-segmenten; beelddata en alle overige segmenten blijven ongewijzigd.

    Na het scanheader (SOS) wordt de scandata ongewijzigd overgenomen; volgt er nog een marker
    (progressieve JPEG), dan wordt die weer als segment behandeld. Alles na EOI vervalt, want
    daar staan bij sommige telefoons extra (meta)gegevens.
    """
    n = len(data)
    out = bytearray(b"\xff\xd8")
    pos = 2
    frame = scan = False
    while True:
        if pos + 2 > n or data[pos] != 0xFF:
            raise _corrupt()
        marker = data[pos + 1]
        if marker == 0xFF:  # vulbyte
            pos += 1
            continue
        if marker == 0xD9:  # EOI
            if not scan:
                raise _corrupt()
            out += b"\xff\xd9"
            return bytes(out)
        if marker in (0x00, 0xD8):
            raise _corrupt()
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # markers zonder lengte
            out += data[pos : pos + 2]
            pos += 2
            continue
        if pos + 4 > n:
            raise _corrupt()
        end = pos + 2 + int.from_bytes(data[pos + 2 : pos + 4], "big")
        if end < pos + 4 or end > n:
            raise _corrupt()
        if marker in _JPEG_SOF:
            frame = True
        if marker == 0xDA:  # SOS
            if not frame:
                raise _corrupt()
            scan = True
            stop = _jpeg_scan_end(data, end)
            out += data[pos:stop]
            pos = stop
            continue
        if marker not in _JPEG_DROP:
            out += data[pos:end]
        pos = end


# --------------------------------------------------------------------------- PNG

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_KEEP = frozenset(
    {
        b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM",
        b"sRGB", b"iCCP", b"sBIT", b"pHYs",
    }
)  # fmt: skip


def _strip_png(data: bytes) -> bytes:
    """Behoudt alleen beeldchunks; tekst-, EXIF- en tijdchunks (tEXt, zTXt, iTXt, eXIf, tIME) vervallen."""
    n = len(data)
    out = bytearray(_PNG_SIGNATURE)
    pos = len(_PNG_SIGNATURE)
    first = True
    image = False
    while True:
        if pos + 8 > n:
            raise _corrupt()
        length = int.from_bytes(data[pos : pos + 4], "big")
        kind = data[pos + 4 : pos + 8]
        end = pos + 12 + length
        if length > 0x7FFFFFFF or end > n or not kind.isalpha():
            raise _corrupt()
        if first and (kind != b"IHDR" or length != 13):
            raise _corrupt()
        first = False
        if kind in _PNG_KEEP:
            if zlib.crc32(data[pos + 4 : end - 4]) != int.from_bytes(data[end - 4 : end], "big"):
                raise _corrupt()
            out += data[pos:end]
        image = image or kind == b"IDAT"
        pos = end
        if kind == b"IEND":  # wat erna komt vervalt
            if not image:
                raise _corrupt()
            return bytes(out)


# --------------------------------------------------------------------------- WebP

_WEBP_DROP = frozenset({b"EXIF", b"XMP "})
_WEBP_IMAGE = frozenset({b"VP8 ", b"VP8L", b"ANMF"})
_VP8X_EXIF_XMP_FLAGS = 0x08 | 0x04


def _strip_webp(data: bytes) -> bytes:
    """Verwijdert de chunks EXIF en `XMP `, wist hun vlaggen in VP8X en corrigeert de RIFF-grootte."""
    if len(data) < 12:
        raise _corrupt()
    riff_end = 8 + int.from_bytes(data[4:8], "little")
    if riff_end < 12 or riff_end > len(data):
        raise _corrupt()
    chunks: list[bytes] = []
    image = False
    pos = 12
    while pos < riff_end:
        if pos + 8 > riff_end:
            raise _corrupt()
        kind = data[pos : pos + 4]
        size = int.from_bytes(data[pos + 4 : pos + 8], "little")
        body_end = pos + 8 + size
        if body_end > riff_end:
            raise _corrupt()
        body = data[pos + 8 : body_end]
        pos = body_end + (size & 1)  # chunks worden op even lengte aangevuld
        if kind in _WEBP_DROP:
            continue
        if kind == b"VP8X":
            if size < 10:
                raise _corrupt()
            body = bytes([body[0] & ~_VP8X_EXIF_XMP_FLAGS & 0xFF]) + body[1:]
        image = image or kind in _WEBP_IMAGE
        chunks.append(kind + size.to_bytes(4, "little") + body + (b"\x00" if size & 1 else b""))
    if not image:
        raise _corrupt()
    payload = b"WEBP" + b"".join(chunks)
    return b"RIFF" + len(payload).to_bytes(4, "little") + payload


# --------------------------------------------------------------------------- publiek


def detect_extension(data: bytes) -> str | None:
    """Bestandsextensie op basis van de magic bytes; None voor al het andere (SVG, GIF, HEIC, ...)."""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == _PNG_SIGNATURE:
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def clean_photo(data: bytes) -> tuple[bytes, str]:
    """Controleert grootte en type en geeft `(opgeschoonde bytes, extensie)`; anders `PhotoError`."""
    if not data:
        raise PhotoError("missing")
    if len(data) > MAX_BYTES:
        raise PhotoError("too_large")
    ext = detect_extension(data)
    if ext is None:
        raise PhotoError("unsupported")
    strip = {".jpg": _strip_jpeg, ".png": _strip_png, ".webp": _strip_webp}[ext]
    return strip(data), ext


def photo_path(photos_dir: Path, name: str | None) -> Path | None:
    """Pad van een opgeslagen foto; None als de naam niet de verwachte vorm heeft."""
    if not name or PHOTO_NAME_RE.fullmatch(name) is None:
        return None
    return photos_dir / name


def write_photo(photos_dir: Path, data: bytes, ext: str) -> str:
    """Schrijft de foto atomisch (tijdelijk bestand + `os.replace`) en geeft de nieuwe naam."""
    name = secrets.token_hex(16) + ext
    existed = photos_dir.is_dir()
    photos_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not existed:
        os.chmod(photos_dir, 0o700)
    tmp = photos_dir / f".{name}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, photos_dir / name)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return name


def remove_photo(photos_dir: Path, name: str | None) -> None:
    """Verwijdert een foto; fouten worden gelogd en nooit doorgegeven."""
    path = photo_path(photos_dir, name)
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("photo_remove_failed type=%s", type(exc).__name__)
