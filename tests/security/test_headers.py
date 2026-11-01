"""Beveiligingsheaders en cachegedrag op HTML, API-JSON, 404 en 401."""

from __future__ import annotations

import pytest


def _basis(r):
    csp = r.headers["content-security-policy"]
    assert "form-action 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert r.headers["permissions-policy"] == "geolocation=(), camera=(), microphone=()"
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
