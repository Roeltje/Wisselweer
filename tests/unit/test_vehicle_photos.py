"""Voertuigfoto's: type op magic bytes, metadata strippen, afkappen en opslag."""

from __future__ import annotations

import logging
import re
import stat
import struct
from pathlib import Path

import pytest

from tests.fixtures.images import (
    EXIF_PAYLOAD,
    FAKE_BITSTREAM,
    GPS_TEXT,
    SCAN_DATA,
    VP8X_ALPHA,
    VP8X_EXIF,
    VP8X_ICC,
    VP8X_XMP,
    jpeg_segment,
    make_jpeg,
    make_jpeg_with_exif,
    make_png,
    make_png_with_text,
    make_webp_with_exif,
    png_chunk,
    riff_chunk,
    riff_webp,
    vp8x,
)
from wisselweer.vehicles import photos
from wisselweer.vehicles.photos import MAX_BYTES, PhotoError, clean_photo


def _code(data: bytes) -> str:
    with pytest.raises(PhotoError) as info:
        clean_photo(data)
    return info.value.code


# --- Type en grootte ---------------------------------------------------------------------


def test_type_wordt_bepaald_op_magic_bytes():
    assert clean_photo(make_jpeg())[1] == ".jpg"
    assert clean_photo(make_png())[1] == ".png"
    assert clean_photo(make_webp_with_exif())[1] == ".webp"


@pytest.mark.parametrize(
    "data",
    [
        b"GIF89a\x01\x00\x01\x00\x00\x00\x00;",
        b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>',
        b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic",
        b"RIFF\x04\x00\x00\x00WAVE",  # RIFF, maar geen WebP
        b"%PDF-1.7\n",
        b"<?php echo 1; ?>",
        b"\xff\xd8",  # te kort om JPEG te heten
    ],
)
def test_ander_type_wordt_geweigerd(data):
    assert _code(data) == "unsupported"


def test_leeg_bestand():
    assert _code(b"") == "missing"


def test_grootte_grens():
    exact = make_jpeg(scan=bytes(MAX_BYTES - len(make_jpeg(scan=b""))))
    assert len(exact) == MAX_BYTES
    assert clean_photo(exact)[1] == ".jpg"
    assert _code(exact + b"\x00") == "too_large"
    # De grootte wordt eerder gecontroleerd dan het type: ook onzin van 3 MB is "te groot".
    assert _code(b"x" * (3 * MAX_BYTES)) == "too_large"


# --- JPEG ---------------------------------------------------------------------------------


def test_jpeg_exif_gps_verdwijnt():
    raw = make_jpeg_with_exif()
    assert b"Exif" in raw and b"GPS" in raw
    out, ext = clean_photo(raw)
    assert ext == ".jpg"
    assert b"Exif" not in out and b"GPS" not in out
    assert out.startswith(b"\xff\xd8") and out.endswith(b"\xff\xd9")


def test_jpeg_segmenten_per_soort():
    dropped = [jpeg_segment(m, b"geheim" + bytes([m])) for m in (*range(0xE1, 0xEE), 0xEF, 0xFE)]
    kept = [jpeg_segment(0xEE, b"Adobe\x00\x64\x00\x00\x00\x00\x01")]
    out, _ = clean_photo(make_jpeg(*dropped, *kept))
    assert b"geheim" not in out
    assert b"JFIF" in out  # APP0
    assert b"Adobe" in out  # APP14
    assert b"\xff\xfe" not in out  # COM
    # Alles wat niet metadata is blijft byte voor byte staan, in dezelfde volgorde.
    assert out == make_jpeg(*kept)


def test_jpeg_scandata_en_rest_ongewijzigd():
    out, _ = clean_photo(make_jpeg_with_exif())
    assert SCAN_DATA in out


def test_jpeg_data_na_eoi_vervalt():
    trailer = b"\xff\xd8" + jpeg_segment(0xE1, EXIF_PAYLOAD) + b"\xff\xd9"
    out, _ = clean_photo(make_jpeg(trailer=trailer))
    assert out == make_jpeg()
    assert b"GPS" not in out


def test_jpeg_progressief_metadata_tussen_scans():
    sos = jpeg_segment(0xDA, b"\x01\x01\x00\x00\x3f\x00")
    raw = (
        make_jpeg().removesuffix(b"\xff\xd9")
        + jpeg_segment(0xE1, EXIF_PAYLOAD)
        + sos
        + b"\x99\xff\xd9"
    )
    out, _ = clean_photo(raw)
    assert b"GPS" not in out
    assert out.count(b"\xff\xda") == 2 and out.endswith(b"\x99\xff\xd9")


def test_jpeg_vulbytes_voor_een_marker():
    raw = make_jpeg()
    raw = raw.replace(b"\xff\xdb", b"\xff\xff\xff\xdb", 1)
    assert clean_photo(raw)[0] == make_jpeg()


def test_jpeg_afgekapt_wordt_geweigerd_op_elke_lengte():
    raw = make_jpeg_with_exif()
    for cut in range(3, len(raw)):
        assert _code(raw[:cut]) == "corrupt", cut


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff\xd8\xff" + b"\x00" * 20,  # geen geldige marker
        b"\xff\xd8" + jpeg_segment(0xE0, b"JFIF") + b"\xff\xd9",  # EOI zonder beeld
        b"\xff\xd8\xff\xe0\x00\x01",  # segmentlengte < 2
        b"\xff\xd8\xff\xe1\xff\xff" + b"x" * 10,  # segment langer dan het bestand
        b"\xff\xd8\xff\xda\x00\x02\x00\xff\xd9",  # scan zonder frameheader
    ],
)
def test_jpeg_kapot_wordt_geweigerd(raw):
    assert _code(raw) == "corrupt"


# --- PNG ----------------------------------------------------------------------------------


def test_png_tekstchunks_verdwijnen():
    raw = make_png(
        png_chunk(b"tEXt", b"Comment\x00" + GPS_TEXT),
        png_chunk(b"zTXt", b"k\x00\x00" + GPS_TEXT),
        png_chunk(b"iTXt", b"k\x00\x00\x00\x00\x00" + GPS_TEXT),
        png_chunk(b"eXIf", EXIF_PAYLOAD),
        png_chunk(b"tIME", struct.pack(">HBBBBB", 2026, 11, 1, 12, 0, 0)),
        png_chunk(b"zzZz", b"onbekend"),
    )
    assert b"GPS" in raw
    out, ext = clean_photo(raw)
    assert ext == ".png"
    for kind in (b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME", b"zzZz", b"GPS"):
        assert kind not in out, kind
    assert out == make_png()


def test_png_beeldchunks_blijven():
    keep = [
        png_chunk(b"gAMA", struct.pack(">I", 45455)),
        png_chunk(b"cHRM", bytes(32)),
        png_chunk(b"sRGB", b"\x00"),
        png_chunk(b"iCCP", b"icc\x00\x00" + b"data"),
        png_chunk(b"sBIT", b"\x08\x08\x08"),
        png_chunk(b"pHYs", struct.pack(">IIB", 2835, 2835, 1)),
        png_chunk(b"PLTE", b"\x00\x00\x00"),
        png_chunk(b"tRNS", b"\x00"),
    ]
    raw = make_png(png_chunk(b"tEXt", b"a\x00b"), *keep)
    assert clean_photo(raw)[0] == make_png(*keep)


def test_png_data_na_iend_vervalt():
    out, _ = clean_photo(make_png(trailer=b"geheim" + GPS_TEXT))
    assert out == make_png()


def test_png_afgekapt_wordt_geweigerd_op_elke_lengte():
    raw = make_png_with_text()
    for cut in range(8, len(raw)):
        assert _code(raw[:cut]) == "corrupt", cut


def test_png_kapot_wordt_geweigerd():
    good = make_png()
    ihdr_end = 8 + 25
    bad_crc = bytearray(good)
    bad_crc[ihdr_end - 1] ^= 0xFF  # CRC van IHDR
    assert _code(bytes(bad_crc)) == "corrupt"
    no_idat = good[:ihdr_end] + png_chunk(b"IEND")
    assert _code(no_idat) == "corrupt"
    no_ihdr = good[:8] + good[ihdr_end:]
    assert _code(no_ihdr) == "corrupt"
    huge = good[:8] + struct.pack(">I", 0xFFFFFFFF) + b"IHDR" + good[16:]
    assert _code(huge) == "corrupt"
    bad_name = good[:12] + b"IH\x00R" + good[16:]
    assert _code(bad_name) == "corrupt"


# --- WebP ---------------------------------------------------------------------------------


def _chunks(webp: bytes) -> list[tuple[bytes, bytes]]:
    assert webp[:4] == b"RIFF" and webp[8:12] == b"WEBP"
    assert struct.unpack("<I", webp[4:8])[0] == len(webp) - 8
    out, pos = [], 12
    while pos < len(webp):
        kind, size = webp[pos : pos + 4], struct.unpack("<I", webp[pos + 4 : pos + 8])[0]
        out.append((kind, webp[pos + 8 : pos + 8 + size]))
        pos += 8 + size + (size & 1)
    assert pos == len(webp)
    return out


def test_webp_exif_en_xmp_verdwijnen_en_vlaggen_worden_gewist():
    raw = make_webp_with_exif()
    assert b"GPS" in raw
    out, ext = clean_photo(raw)
    assert ext == ".webp"
    assert b"EXIF" not in out and b"XMP " not in out and b"GPS" not in out
    chunks = _chunks(out)
    assert [kind for kind, _ in chunks] == [b"VP8X", b"ICCP", b"VP8 "]
    flags = chunks[0][1][0]
    assert flags & (VP8X_EXIF | VP8X_XMP) == 0
    assert flags & (VP8X_ICC | VP8X_ALPHA) == VP8X_ICC | VP8X_ALPHA  # overige vlaggen blijven
    assert chunks[0][1][1:] == raw[12 + 8 + 1 : 12 + 8 + 10]  # rest van VP8X ongewijzigd
    assert chunks[2][1] == FAKE_BITSTREAM


def test_webp_zonder_metadata_blijft_gelijk():
    raw = riff_webp(riff_chunk(b"VP8 ", FAKE_BITSTREAM))
    assert clean_photo(raw)[0] == raw
    raw = riff_webp(vp8x(VP8X_ALPHA), riff_chunk(b"VP8L", FAKE_BITSTREAM))
    assert clean_photo(raw)[0] == raw


def test_webp_data_buiten_riff_vervalt():
    raw = riff_webp(riff_chunk(b"VP8 ", FAKE_BITSTREAM))
    assert clean_photo(raw + b"geheim" + GPS_TEXT)[0] == raw


def test_webp_afgekapt_wordt_geweigerd_op_elke_lengte():
    raw = make_webp_with_exif()
    for cut in range(12, len(raw)):
        assert _code(raw[:cut]) == "corrupt", cut


def test_webp_kapot_wordt_geweigerd():
    assert _code(b"RIFF\x04\x00\x00\x00WEBP") == "corrupt"  # geen beeldchunk
    assert _code(riff_webp(riff_chunk(b"EXIF", b"x"))) == "corrupt"
    assert _code(riff_webp(riff_chunk(b"VP8X", b"\x08\x00"))) == "corrupt"  # VP8X te kort
    overrun = riff_webp(riff_chunk(b"VP8 ", FAKE_BITSTREAM))
    overrun = overrun[:16] + struct.pack("<I", 1000) + overrun[20:]
    assert _code(overrun) == "corrupt"
    assert _code(b"RIFF\x02\x00\x00\x00WEBP") == "corrupt"  # RIFF-grootte kleiner dan de kop
    assert _code(b"RIFF\x00\x00\x00") == "unsupported"


# --- Namen en opslag ------------------------------------------------------------------------


def test_photo_path_accepteert_alleen_de_eigen_vorm(tmp_path):
    good = "0123456789abcdef0123456789abcdef"
    for ext in ("webp", "jpg", "png"):
        assert photos.photo_path(tmp_path, f"{good}.{ext}") == tmp_path / f"{good}.{ext}"
    for bad in (
        None,
        "",
        "../../etc/passwd",
        f"../{good}.jpg",
        f"sub/{good}.jpg",
        f"{good}/../{good}.jpg",
        f"/{good}.jpg",
        f"{good}.jpg\n",
        f"{good}.JPG",
        f"{good}.jpeg",
        f"{good}.svg",
        f"{good}.jpg.php",
        f"{good.upper()}.jpg",
        f"{good[:-1]}.jpg",
        f"{good}0.jpg",
        f".{good}.jpg.tmp",
        f"{good}.jpg\x00.png",
        "..\\x.jpg",
    ):
        assert photos.photo_path(tmp_path, bad) is None, bad


def test_write_photo_maakt_privemap_en_privebestand(tmp_path):
    folder = tmp_path / "nieuw" / "photos"
    name = photos.write_photo(folder, b"abc", ".png")
    assert re.fullmatch(r"[0-9a-f]{32}\.png", name)
    assert (folder / name).read_bytes() == b"abc"
    assert stat.S_IMODE((folder / name).stat().st_mode) == 0o600
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert [p.name for p in folder.iterdir()] == [name]  # geen tijdelijk bestand over
    assert photos.write_photo(folder, b"abc", ".png") != name  # willekeurige naam


def test_write_photo_laat_bestaande_map_ongemoeid(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir(mode=0o750)
    folder.chmod(0o750)
    photos.write_photo(folder, b"x", ".jpg")
    assert stat.S_IMODE(folder.stat().st_mode) == 0o750


def test_write_photo_ruimt_tijdelijk_bestand_op_bij_een_fout(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise OSError("schijf vol")

    monkeypatch.setattr(photos.os, "replace", boom)
    with pytest.raises(OSError):
        photos.write_photo(tmp_path, b"x", ".jpg")
    assert list(tmp_path.iterdir()) == []


def test_remove_photo(tmp_path):
    name = photos.write_photo(tmp_path, b"x", ".jpg")
    photos.remove_photo(tmp_path, name)
    assert not (tmp_path / name).exists()
    photos.remove_photo(tmp_path, name)  # bestaat niet meer: geen fout
    photos.remove_photo(tmp_path, None)
    outside = tmp_path.parent / "buiten.jpg"
    outside.write_bytes(b"x")
    photos.remove_photo(tmp_path, "../buiten.jpg")  # ongeldige naam wordt genegeerd
    assert outside.exists()


def test_remove_photo_logt_fouten_zonder_te_crashen(tmp_path, monkeypatch, caplog):
    name = photos.write_photo(tmp_path, b"x", ".jpg")

    def deny(self, missing_ok=False):
        raise PermissionError("geen rechten")

    monkeypatch.setattr(Path, "unlink", deny)
    with caplog.at_level(logging.WARNING, logger="wisselweer.photos"):
        photos.remove_photo(tmp_path, name)
    assert "photo_remove_failed type=PermissionError" in caplog.text
    assert name not in caplog.text
