"""Beveiligingsheaders en cachegedrag op HTML, API-JSON, 404 en 401."""

from __future__ import annotations

import pytest


def _basis(r):
    csp = r.headers["content-security-policy"]
    assert "form-action 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert r.headers["permissions-policy"] == "geolocation=(self), camera=(), microphone=()"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_headers_op_html(client):
    r = client.get("/login")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    _basis(r)
    assert r.headers["cache-control"] == "no-store"


def test_headers_op_html_ingelogd(session_client):
    r = session_client.get("/")
    assert r.status_code == 200
    _basis(r)
    assert r.headers["cache-control"] == "no-store"


def test_headers_op_api_json(app, client, token):
    r = client.get("/api/v1/vehicles", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    _basis(r)
    assert r.headers["cache-control"] == "no-store"


def test_headers_op_401(client):
    r = client.get("/api/v1/vehicles")
    assert r.status_code == 401
    _basis(r)
    assert r.headers["cache-control"] == "no-store"


def test_headers_op_404(client):
    for pad in ("/bestaat-niet", "/api/v1/bestaat-niet"):
        r = client.get(pad)
        assert r.status_code == 404
        _basis(r)
        assert r.headers["cache-control"] == "no-store"


def test_headers_op_redirect(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    _basis(r)
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("pad", ["/api/v1/health", "/static/app.css"])
def test_geen_no_store_op_health_en_static(client, pad):
    r = client.get(pad)
    assert r.status_code == 200
    _basis(r)
    assert "no-store" not in r.headers.get("cache-control", "")


def test_foto_is_cachebaar_maar_alleen_voor_ingelogde_gebruikers(
    client, session_client, csrf, token
):
    from tests.fixtures.images import make_jpeg

    body = {
        "name": "Testauto",
        "location": {"name": "Utrecht", "latitude": 52.09, "longitude": 5.12},
    }
    bearer = {"Authorization": f"Bearer {token}"}
    vid = client.post("/api/v1/vehicles", json=body, headers=bearer).json()["id"]
    r = session_client.post(
        f"/vehicles/{vid}/photo",
        data={"csrf_token": csrf},
        files={"photo": ("foto.jpg", make_jpeg(), "image/jpeg")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = session_client.get(f"/vehicles/{vid}/photo")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["content-disposition"] == "inline"
    assert r.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert r.headers["content-security-policy"] == "default-src 'none'; sandbox"
    # Alleen de foto is cachebaar; pagina's en API-antwoorden blijven no-store.
    assert session_client.get(f"/vehicles/{vid}").headers["cache-control"] == "no-store"
    api = session_client.get(f"/api/v1/vehicles/{vid}")
    assert api.headers["cache-control"] == "no-store" and api.json()["has_photo"] is True
    # Zonder sessie (ook met een geldig API-token) geen foto.
    session_client.cookies.clear()
    r = session_client.get(f"/vehicles/{vid}/photo", headers=bearer, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
