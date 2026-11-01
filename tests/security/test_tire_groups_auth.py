"""Auth en CSRF op de endpoints voor bandengroepen."""

from __future__ import annotations

import pytest

API = "/api/v1"
ROUTES = [
    ("post", f"{API}/tire-sets/1/tire-groups", {}),
    ("patch", f"{API}/tire-groups/1", {}),
    ("delete", f"{API}/tire-groups/1", None),
    ("post", f"{API}/tire-sets/1/replace", {"group_id": 1}),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_zonder_inlog_401(client, method, path, body):
    kw = {} if body is None else {"json": body}
    r = getattr(client, method)(path, **kw)
    assert r.status_code == 401 and r.json() == {"detail": "unauthorized"}


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_sessie_zonder_csrf_403(session_client, csrf, method, path, body):
    kw = {} if body is None else {"json": body}
    r = getattr(session_client, method)(path, **kw)
    assert r.status_code == 403 and r.json() == {"detail": "csrf_failed"}
    r = getattr(session_client, method)(path, headers={"X-CSRF-Token": "fout"}, **kw)
    assert r.status_code == 403
    # Met geldig token komt de aanvraag door de CSRF-controle (de set bestaat niet: 404).
    r = getattr(session_client, method)(path, headers={"X-CSRF-Token": csrf}, **kw)
    assert r.status_code == 404


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_bearer_zonder_csrf_werkt(client, token, method, path, body):
    kw = {} if body is None else {"json": body}
    r = getattr(client, method)(path, headers={"Authorization": f"Bearer {token}"}, **kw)
    assert r.status_code == 404
