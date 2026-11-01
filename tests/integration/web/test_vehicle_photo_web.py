"""Foto per voertuig via de webinterface: uploaden, vervangen, verwijderen, serveren en weergave."""

from __future__ import annotations

import re
import stat

import pytest
from sqlalchemy import select

from tests.fixtures.auth import bearer
from tests.fixtures.images import (
    GPS_TEXT,
    make_jpeg,
    make_jpeg_with_exif,
    make_png_with_text,
    make_webp_with_exif,
)
from tests.integration.web.conftest import create_vehicle
from wisselweer.api.deps import ensure_db
from wisselweer.storage.orm import Vehicle
from wisselweer.vehicles.photos import MAX_BYTES

NAME_RE = re.compile(r"[0-9a-f]{32}\.(?:webp|jpg|png)")


def photos_dir(web):
    return web.c.app.state.settings.photos_dir


def stored(web, vid: int) -> str | None:
    with ensure_db(web.c.app)() as s:
        return s.scalar(select(Vehicle.photo).where(Vehicle.id == vid))


def upload(web, vid, content, *, filename="foto.jpg", ctype="image/jpeg", csrf="auto"):
    token = web.token() if csrf == "auto" else csrf
    data = {"csrf_token": token} if token is not None else {}
    files = {"photo": (filename, content, ctype)} if content is not None else None
    return web.c.post(f"/vehicles/{vid}/photo", data=data, files=files, follow_redirects=False)


def files_in(web) -> list[str]:
    d = photos_dir(web)
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def flash_after(web, vid) -> str:
    html = web.get(f"/vehicles/{vid}").text
    m = re.search(r'<p class="flash [^"]*"[^>]*>(.*?)</p>', html, re.S)
    return m.group(1) if m else ""


# --- Uploaden --------------------------------------------------------------------------------


def test_upload_jpeg_met_exif_slaat_opgeschoond_bestand_op(web):
    vid = create_vehicle(web)
    r = upload(web, vid, make_jpeg_with_exif())
    assert r.status_code == 303 and r.headers["location"] == f"/vehicles/{vid}#photo"
    name = stored(web, vid)
    assert NAME_RE.fullmatch(name) and name.endswith(".jpg")
    path = photos_dir(web) / name
    data = path.read_bytes()
    assert b"Exif" not in data and b"GPS" not in data and data.startswith(b"\xff\xd8")
    assert files_in(web) == [name]  # geen tijdelijke bestanden
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(photos_dir(web).stat().st_mode) == 0o700
    assert "Foto opgeslagen" in flash_after(web, vid)


def test_upload_png_en_webp_zonder_metadata(web):
    vid = create_vehicle(web)
    assert (
        upload(web, vid, make_png_with_text(), filename="a.png", ctype="image/png").status_code
        == 303
    )
    name = stored(web, vid)
    assert name.endswith(".png") and b"tEXt" not in (photos_dir(web) / name).read_bytes()
    assert (
        upload(web, vid, make_webp_with_exif(), filename="a.webp", ctype="image/webp").status_code
        == 303
    )
    name = stored(web, vid)
    data = (photos_dir(web) / name).read_bytes()
    assert name.endswith(".webp") and b"EXIF" not in data and GPS_TEXT not in data


def test_bestandsnaam_en_contenttype_van_de_gebruiker_tellen_niet(web):
    vid = create_vehicle(web)
    r = upload(web, vid, make_png_with_text(), filename="../../evil.php", ctype="text/html")
    assert r.status_code == 303
    (name,) = files_in(web)
    assert NAME_RE.fullmatch(name) and name.endswith(".png")  # extensie volgt de inhoud
    assert stored(web, vid) == name
    # Andersom: een .png-naam met JPEG-inhoud wordt een .jpg.
    upload(web, vid, make_jpeg(), filename="x.png", ctype="image/png")
    assert stored(web, vid).endswith(".jpg")


def test_vervangen_verwijdert_het_oude_bestand(web):
    vid = create_vehicle(web)
    upload(web, vid, make_jpeg())
    old = stored(web, vid)
    assert f"?v={old[:8]}" in web.get(f"/vehicles/{vid}").text
    upload(web, vid, make_jpeg_with_exif())
    new = stored(web, vid)
    assert new != old
    assert files_in(web) == [new]
    page = web.get(f"/vehicles/{vid}").text
    assert f"?v={new[:8]}" in page and f"?v={old[:8]}" not in page  # nieuwe URL breekt de cache


def test_verwijderen(web):
    vid = create_vehicle(web)
    assert web.post(f"/vehicles/{vid}/photo/delete").status_code == 303  # zonder foto: geen fout
    upload(web, vid, make_jpeg())
    assert files_in(web)
    r = web.post(f"/vehicles/{vid}/photo/delete")
    assert r.status_code == 303 and r.headers["location"] == f"/vehicles/{vid}#photo"
    assert stored(web, vid) is None and files_in(web) == []
    assert "Foto verwijderd" in flash_after(web, vid)
    assert web.get(f"/vehicles/{vid}/photo").status_code == 404


def test_voertuig_verwijderen_verwijdert_de_foto(web):
    vid = create_vehicle(web)
    other = create_vehicle(web, name="Andere auto")
    upload(web, vid, make_jpeg())
    upload(web, other, make_jpeg())
    mine = stored(web, vid)
    assert web.post(f"/vehicles/{vid}/delete").status_code == 303
    assert files_in(web) == [stored(web, other)] and mine not in files_in(web)


def test_voertuig_verwijderen_via_de_api_verwijdert_de_foto(web):
    vid = create_vehicle(web)
    upload(web, vid, make_jpeg())
    assert len(files_in(web)) == 1
    r = web.c.delete(f"/api/v1/vehicles/{vid}", headers=bearer(web.c.app))
    assert r.status_code == 204
    assert files_in(web) == []


# --- Weigeringen ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "filename", "ctype"),
    [
        (b"GIF89a\x01\x00\x01\x00\x00\x00\x00;", "a.gif", "image/gif"),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            "a.svg",
            "image/svg+xml",
        ),
        (b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00", "a.heic", "image/heic"),
        (b"<?php echo 1;", "a.jpg", "image/jpeg"),  # liegt over het type
        (b"gewoon tekst", "a.png", "image/png"),
    ],
)
def test_verkeerd_type_wordt_geweigerd(web, content, filename, ctype):
    vid = create_vehicle(web)
    r = upload(web, vid, content, filename=filename, ctype=ctype)
    assert r.status_code == 303
    assert "wordt niet ondersteund" in flash_after(web, vid)
    assert stored(web, vid) is None and files_in(web) == []


def test_te_groot_wordt_geweigerd(web):
    vid = create_vehicle(web)
    just_over = b"\xff\xd8\xff" + bytes(MAX_BYTES - 2)
    assert len(just_over) == MAX_BYTES + 1
    assert upload(web, vid, just_over).status_code == 303
    assert "te groot" in flash_after(web, vid)
    assert upload(web, vid, make_jpeg(scan=bytes(5 * MAX_BYTES))).status_code == 303
    assert "te groot" in flash_after(web, vid)
    assert stored(web, vid) is None and files_in(web) == []


def test_precies_de_maximale_grootte_mag(web):
    vid = create_vehicle(web)
    exact = make_jpeg(scan=bytes(MAX_BYTES - len(make_jpeg(scan=b""))))
    assert len(exact) == MAX_BYTES
    assert upload(web, vid, exact).status_code == 303
    assert stored(web, vid) is not None


def test_afgekapte_foto_wordt_geweigerd(web):
    vid = create_vehicle(web)
    raw = make_jpeg_with_exif()
    assert upload(web, vid, raw[: len(raw) // 2]).status_code == 303
    assert "beschadigd" in flash_after(web, vid)
    assert stored(web, vid) is None and files_in(web) == []


def test_geweigerde_upload_laat_de_bestaande_foto_staan(web):
    vid = create_vehicle(web)
    upload(web, vid, make_jpeg())
    name = stored(web, vid)
    upload(web, vid, b"GIF89a")
    assert stored(web, vid) == name and files_in(web) == [name]


def test_geen_bestand_gekozen(web):
    vid = create_vehicle(web)
    r = upload(web, vid, None)  # formulier zonder bestandsveld
    assert r.status_code == 303 and "Kies eerst een foto" in flash_after(web, vid)
    r = upload(web, vid, b"", filename="")  # leeg bestandsveld, zoals een browser zonder keuze
    assert r.status_code == 303 and "Kies eerst een foto" in flash_after(web, vid)
    assert stored(web, vid) is None


def test_onbekend_voertuig(web):
    assert upload(web, 999, make_jpeg()).status_code == 404
    assert web.get("/vehicles/999/photo").status_code == 404
    assert web.post("/vehicles/999/photo/delete").status_code == 404
    assert files_in(web) == []


# --- CSRF en inloggen --------------------------------------------------------------------------


@pytest.mark.parametrize("token", [None, "", "fout"])
def test_zonder_geldig_csrf_token_geweigerd(web, token):
    vid = create_vehicle(web)
    r = upload(web, vid, make_jpeg(), csrf=token)
    assert r.status_code == 403
    assert stored(web, vid) is None and files_in(web) == []


def test_verwijderen_zonder_csrf_token_geweigerd(web):
    vid = create_vehicle(web)
    upload(web, vid, make_jpeg())
    r = web.c.post(f"/vehicles/{vid}/photo/delete", data={}, follow_redirects=False)
    assert r.status_code == 403
    assert stored(web, vid) is not None


def test_zonder_login_geen_foto_en_geen_upload(web):
    vid = create_vehicle(web)
    upload(web, vid, make_jpeg())
    assert len(files_in(web)) == 1
    token = web.token()
    web.c.cookies.clear()
    r = web.c.get(f"/vehicles/{vid}/photo", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert r.content == b""
    r = web.c.post(
        f"/vehicles/{vid}/photo",
        data={"csrf_token": token},
        files={"photo": ("a.jpg", make_jpeg(), "image/jpeg")},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    r = web.c.post(
        f"/vehicles/{vid}/photo/delete", data={"csrf_token": token}, follow_redirects=False
    )
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert len(files_in(web)) == 1  # niets veranderd


def test_bearer_token_geeft_geen_toegang_tot_de_fotoroute(web):
    vid = create_vehicle(web)
    upload(web, vid, make_jpeg())
    web.c.cookies.clear()
    r = web.c.get(f"/vehicles/{vid}/photo", headers=bearer(web.c.app), follow_redirects=False)
    assert r.status_code == 303  # alleen webpagina's (sessie), zoals de rest van de interface


# --- Serveren ------------------------------------------------------------------------------------


def test_404_zonder_foto(web):
    vid = create_vehicle(web)
    r = web.get(f"/vehicles/{vid}/photo")
    assert r.status_code == 404
    assert r.headers["cache-control"] == "no-store"


def test_headers_van_de_fotoresponse(web):
    vid = create_vehicle(web)
    upload(web, vid, make_jpeg_with_exif())
    name = stored(web, vid)
    r = web.get(f"/vehicles/{vid}/photo?v={name[:8]}")
    assert r.status_code == 200
    assert r.content == (photos_dir(web) / name).read_bytes()
    h = r.headers
    assert h["content-type"] == "image/jpeg"
    assert h["x-content-type-options"] == "nosniff"
    assert h["content-disposition"] == "inline"
    assert h["content-security-policy"] == "default-src 'none'; sandbox"
    assert h["cache-control"] == "private, max-age=31536000, immutable"
    assert "no-store" not in h["cache-control"]
    assert h["x-frame-options"] == "DENY" and h["referrer-policy"] == "no-referrer"
    # Alle andere responses blijven no-store.
    assert web.get(f"/vehicles/{vid}").headers["cache-control"] == "no-store"
    assert web.get("/").headers["cache-control"] == "no-store"
    assert web.get("/vehicles/999/photo").headers["cache-control"] == "no-store"


def test_contenttype_volgt_de_extensie(web):
    vid = create_vehicle(web)
    for content, ctype in (
        (make_png_with_text(), "image/png"),
        (make_webp_with_exif(), "image/webp"),
        (make_jpeg(), "image/jpeg"),
    ):
        upload(web, vid, content)
        assert web.get(f"/vehicles/{vid}/photo").headers["content-type"] == ctype


@pytest.mark.parametrize(
    "bad",
    [
        "../../buiten.jpg",
        "../buiten.jpg",
        "/etc/passwd",
        "0123456789abcdef0123456789abcdef.svg",
        "0123456789ABCDEF0123456789ABCDEF.jpg",
        "0123456789abcdef0123456789abcdef.jpg.php",
    ],
)
def test_ongeldige_opgeslagen_naam_wordt_nooit_geserveerd(web, bad):
    vid = create_vehicle(web)
    (photos_dir(web).parent / "buiten.jpg").write_bytes(b"\xff\xd8\xff geheim")
    with ensure_db(web.c.app)() as s:
        s.get(Vehicle, vid).photo = bad
        s.commit()
    assert web.get(f"/vehicles/{vid}/photo").status_code == 404


def test_naam_in_database_zonder_bestand_geeft_404(web):
    vid = create_vehicle(web)
    with ensure_db(web.c.app)() as s:
        s.get(Vehicle, vid).photo = "0123456789abcdef0123456789abcdef.jpg"
        s.commit()
    assert web.get(f"/vehicles/{vid}/photo").status_code == 404


# --- Weergave --------------------------------------------------------------------------------------


def test_detailpagina_zonder_foto_blijft_zoals_het_was(web):
    vid = create_vehicle(web)
    html = web.get(f"/vehicles/{vid}").text
    assert "vehicle-photo" not in html and "/photo?v=" not in html
    assert "/photo/delete" not in html  # geen verwijderknop zonder foto
    assert "Foto toevoegen" in html
    assert "vehicle-thumb" not in web.get("/").text


def test_detailpagina_toont_foto_bovenaan_en_formulier(web):
    vid = create_vehicle(web, name="Testauto")
    upload(web, vid, make_jpeg())
    name = stored(web, vid)
    html = web.get(f"/vehicles/{vid}").text
    img = re.search(r'<figure class="vehicle-photo">\s*(<img [^>]*>)', html)
    assert img, html[:2000]
    tag = img.group(1)
    assert f'src="/vehicles/{vid}/photo?v={name[:8]}"' in tag
    assert 'width="1200"' in tag and 'height="675"' in tag and 'alt="Testauto"' in tag
    assert html.index("vehicle-photo") < html.index('id="sec-advice"')  # bovenaan
    form = re.search(r"<form[^>]*data-photo-form[^>]*>", html).group(0)
    assert 'enctype="multipart/form-data"' in form and 'method="post"' in form
    file_input = re.search(r'<input[^>]*type="file"[^>]*>', html).group(0)
    assert 'accept="image/jpeg,image/png,image/webp"' in file_input
    assert "capture" not in file_input  # camera én fotobibliotheek
    assert "Foto vervangen" in html
    assert f'action="/vehicles/{vid}/photo/delete"' in html and "data-confirm=" in html


def test_scripts_zijn_extern_en_csp_conform(web):
    vid = create_vehicle(web)
    html = web.get(f"/vehicles/{vid}").text
    assert re.search(r'<script src="/static/photo\.js\?v=[0-9a-f]+" defer>', html)
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)  # geen inline script
    assert web.get("/static/photo.js").status_code == 200
    assert "default-src 'self'" in web.get(f"/vehicles/{vid}").headers["content-security-policy"]


def test_dashboard_toont_kleine_foto(web):
    with_photo = create_vehicle(web, name="Met foto")
    create_vehicle(web, name="Zonder foto")
    upload(web, with_photo, make_jpeg())
    name = stored(web, with_photo)
    html = web.get("/").text
    assert html.count("vehicle-thumb") == 1
    tag = re.search(r'<img class="vehicle-thumb"[^>]*>', html).group(0)
    assert f'src="/vehicles/{with_photo}/photo?v={name[:8]}"' in tag
    assert 'loading="lazy"' in tag and 'width="96"' in tag and 'height="72"' in tag


# --- API --------------------------------------------------------------------------------------------


def test_api_geeft_has_photo_terug(web):
    vid = create_vehicle(web)
    headers = bearer(web.c.app)
    one = web.c.get(f"/api/v1/vehicles/{vid}", headers=headers).json()
    assert one["has_photo"] is False
    upload(web, vid, make_jpeg())
    one = web.c.get(f"/api/v1/vehicles/{vid}", headers=headers).json()
    assert one["has_photo"] is True
    (listed,) = web.c.get("/api/v1/vehicles", headers=headers).json()
    assert listed["has_photo"] is True
    # Geen bestandsnaam of versie in de API-uitvoer.
    name = stored(web, vid)
    for payload in (one, listed):
        assert "photo" not in payload and "photo_version" not in payload
        assert name not in str(payload) and name[:8] not in str(payload)
    web.post(f"/vehicles/{vid}/photo/delete")
    assert web.c.get(f"/api/v1/vehicles/{vid}", headers=headers).json()["has_photo"] is False


def test_api_patch_en_post_geven_has_photo(web):
    headers = bearer(web.c.app)
    body = {
        "name": "Via API",
        "location": {"name": "Utrecht", "latitude": 52.09, "longitude": 5.12},
    }
    r = web.c.post("/api/v1/vehicles", json=body, headers=headers)
    assert r.status_code == 201 and r.json()["has_photo"] is False
    vid = r.json()["id"]
    upload(web, vid, make_jpeg())
    r = web.c.patch(f"/api/v1/vehicles/{vid}", json={"notes": "x"}, headers=headers)
    assert r.status_code == 200 and r.json()["has_photo"] is True
    assert stored(web, vid) is not None  # een PATCH laat de foto staan
