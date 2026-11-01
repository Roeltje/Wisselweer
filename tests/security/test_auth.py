from __future__ import annotations

import hashlib
import logging
import re
import sys
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tests.fixtures.auth import ADMIN_PASSWORD, ADMIN_USER
from tests.security.conftest import csrf_from, login
from wisselweer import cli
from wisselweer.api import auth
from wisselweer.api.deps import ensure_db
from wisselweer.settings import Settings
from wisselweer.storage.orm import AdminUser, ApiToken

V = "/api/v1/vehicles"


def _api_routes(app):
    out = []
    for path, ops in app.openapi()["paths"].items():
        if path.startswith("/api/v1") and path != "/api/v1/health":
            for m in ops:
                out.append((m.upper(), re.sub(r"\{[^}]+\}", "1", path)))
    return out


def test_all_api_routes_require_auth(app, client):
    routes = _api_routes(app)
    assert len(routes) > 25
    for method, path in routes:
        r = client.request(method, path, json={})
        assert r.status_code == 401, (method, path, r.status_code)
        assert r.json() == {"detail": "unauthorized"}


def test_health_is_public(client):
    assert client.get("/api/v1/health").status_code == 200


def test_docs_not_reachable_without_login(client):
    r = client.get("/docs", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")
    assert client.get("/openapi.json").status_code == 401
    assert client.get("/redoc").status_code == 404


def test_docs_after_login(session_client):
    r = session_client.get("/docs")
    assert r.status_code == 200 and "swagger" in r.text.lower()
    csp = r.headers["content-security-policy"]
    # Vaste versie, en de CSP beperkt de CDN tot precies dat pad-prefix.
    prefix = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/"
    assert f"script-src 'self' 'unsafe-inline' {prefix};" in csp
    assert f"style-src 'self' 'unsafe-inline' {prefix};" in csp
    assert "https://cdn.jsdelivr.net;" not in csp and "tiangolo" not in csp
    assert f"{prefix}swagger-ui-bundle.js" in r.text and f"{prefix}swagger-ui.css" in r.text
    assert "swagger-ui-dist@5/" not in r.text
    assert "paths" in session_client.get("/openapi.json").json()
    # De CSP-uitbreiding geldt alleen voor /docs.
    assert "jsdelivr" not in session_client.get("/api/v1/health").headers["content-security-policy"]


@pytest.fixture
def geen_docs_client(tmp_path):
    from fastapi.testclient import TestClient

    from tests.fixtures.auth import make_admin
    from wisselweer.api.app import create_app

    app = create_app(Settings(_env_file=None, data_dir=tmp_path / "data", enable_docs=False))
    make_admin(app)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_docs_uitgezet(geen_docs_client):
    c = geen_docs_client
    for pad in ("/docs", "/openapi.json", "/redoc"):
        assert c.get(pad, follow_redirects=False).status_code == 404
    assert login(c).status_code == 303  # inloggen blijft werken
    for pad in ("/docs", "/openapi.json"):
        assert c.get(pad, follow_redirects=False).status_code == 404
    assert c.get("/api/v1/health").status_code == 200


def test_docs_staat_standaard_aan():
    assert Settings(_env_file=None).enable_docs is True
    assert Settings(_env_file=None, enable_docs="false").enable_docs is False


def test_login_ok_and_wrong(client):
    assert login(client, "verkeerd-wachtwoord").status_code == 401
    r = login(client, "verkeerd-wachtwoord")
    assert "Onjuiste gebruikersnaam of wachtwoord" in r.text
    ok = login(client)
    assert ok.status_code == 303 and ok.headers["location"] == "/"
    assert client.get(V).status_code == 200


def test_unknown_user_same_message(client):
    page = client.get("/login")
    r = client.post(
        "/login",
        data={"username": "nobody", "password": "x" * 12, "csrf_token": csrf_from(page.text)},
    )
    assert r.status_code == 401 and "Onjuiste gebruikersnaam of wachtwoord" in r.text


def test_login_rate_limit(client):
    for _ in range(5):
        assert login(client, "verkeerd-wachtwoord").status_code == 401
    assert login(client, "verkeerd-wachtwoord").status_code == 429
    assert login(client).status_code == 429  # ook juist wachtwoord is geblokkeerd


def test_login_requires_csrf(client):
    client.get("/login")
    r = client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    assert r.status_code == 403 and r.json() == {"detail": "csrf_failed"}
    r = client.post(
        "/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASSWORD, "csrf_token": "fout"},
    )
    assert r.status_code == 403


def test_login_page_without_admin(tmp_path):
    from fastapi.testclient import TestClient

    from wisselweer.api.app import create_app

    app = create_app(Settings(_env_file=None, data_dir=tmp_path / "d"))
    r = TestClient(app).get("/login")
    assert "wisselweer create-admin" in r.text and "<form" not in r.text
    assert "docker compose exec wisselweer wisselweer create-admin" in r.text
    assert "installatiemap" in r.text  # Docker: het commando draait vanuit de map met compose.yaml


@pytest.mark.parametrize("method", ["post", "patch", "delete"])
def test_csrf_missing_or_wrong_is_403(session_client, csrf, method):
    path = V if method == "post" else f"{V}/1"
    body = {"json": {}} if method != "delete" else {}
    r = getattr(session_client, method)(path, **body)
    assert r.status_code == 403 and r.json() == {"detail": "csrf_failed"}
    r = getattr(session_client, method)(path, headers={"X-CSRF-Token": "fout"}, **body)
    assert r.status_code == 403


def test_csrf_header_and_form_field_accepted(session_client, csrf):
    r = session_client.post(V, json={}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 422  # CSRF akkoord, validatie faalt
    r = session_client.post(V, data={"csrf_token": csrf})
    assert r.status_code == 422
    assert session_client.get(V).status_code == 200  # GET heeft geen CSRF nodig


def test_logout_requires_csrf_and_ends_session(session_client, csrf):
    assert session_client.post("/logout").status_code == 403
    r = session_client.post("/logout", headers={"X-CSRF-Token": csrf}, follow_redirects=False)
    assert r.status_code == 303
    assert session_client.get(V).status_code == 401


def test_bearer_token_works_without_csrf(client, token):
    h = {"Authorization": f"Bearer {token}"}
    assert client.get(V, headers=h).status_code == 200
    assert client.post(V, json={}, headers=h).status_code == 422  # geen 403


def test_bad_bearer_rejected_and_no_session_fallback(session_client):
    r = session_client.get(V, headers={"Authorization": "Bearer wwt_onzin"})
    assert r.status_code == 401


def test_revoked_token_rejected(app, client, token):
    h = {"Authorization": f"Bearer {token}"}
    assert client.get(V, headers=h).status_code == 200
    with ensure_db(app)() as s:
        auth.revoke_api_token(s, "test")
        s.commit()
    assert client.get(V, headers=h).status_code == 401


def test_token_stored_only_as_hash(app, token):
    with ensure_db(app)() as s:
        row = s.scalar(select(ApiToken))
        assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in row.token_hash


@pytest.mark.parametrize(
    "target",
    ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "evil"],
)
def test_open_redirect_blocked(client, target):
    r = login(client, next_=target)
    assert r.status_code == 303 and r.headers["location"] == "/"
    page = client.get("/login", params={"next": target})
    assert "evil" not in page.text


def test_relative_next_is_kept(client):
    assert login(client, next_="/vehicles?x=1").headers["location"] == "/vehicles?x=1"


def test_safe_next_unit():
    assert auth.safe_next("/a/b?c=d") == "/a/b?c=d"
    for bad in (None, "", "http://x", "//x", "/\\x", "/a\r\nb", "x", "/login"):
        assert auth.safe_next(bad) == "/"


def test_session_cookie_flags(client):
    r = login(client)
    cookie = r.headers["set-cookie"].lower()
    assert "ww_session=" in cookie
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert "max-age=604800" in cookie
    assert "secure" not in cookie.replace("samesite", "")


def test_cookie_secure_flag(tmp_path):
    from fastapi.testclient import TestClient

    from tests.fixtures.auth import make_admin
    from wisselweer.api.app import create_app

    app = create_app(Settings(_env_file=None, data_dir=tmp_path / "d", cookie_secure=True))
    make_admin(app)
    c = TestClient(app, base_url="https://testserver")
    assert "secure" in login(c).headers["set-cookie"].lower().split("; ")


def test_session_rotated_on_login(client):
    page = client.get("/login")
    before = csrf_from(page.text)
    login_resp = login(client)
    assert login_resp.status_code == 303
    assert before not in str(client.cookies.get("ww_session"))


def test_password_change_invalidates_session(app, session_client):
    assert session_client.get(V).status_code == 200
    with ensure_db(app)() as s:
        auth.reset_password(s, ADMIN_USER, "nieuw-wachtwoord-123")
        s.commit()
    assert session_client.get(V).status_code == 401


def test_password_hash_has_no_plaintext(app):
    with ensure_db(app)() as s:
        h = s.scalar(select(AdminUser)).password_hash
    assert ADMIN_PASSWORD not in h and h.startswith("scrypt$65536$8$2$")
    assert auth.verify_password(ADMIN_PASSWORD, h)
    assert not auth.verify_password("anders-wachtwoord", h)
    assert auth.hash_password(ADMIN_PASSWORD) != h  # willekeurige salt
    assert not auth.verify_password("x", "kapot")
    assert not auth.needs_rehash(h)


def _oude_hash(password: str) -> str:
    """Hash zoals vóór de verhoging: scrypt N=2**14, r=8, p=1."""
    salt = b"s" * 16
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    b64 = auth._b64
    return f"scrypt$16384$8$1${b64(salt)}${b64(digest)}"


def test_old_hash_still_verifies_and_needs_rehash():
    old = _oude_hash(ADMIN_PASSWORD)
    assert auth.verify_password(ADMIN_PASSWORD, old)
    assert not auth.verify_password("anders-wachtwoord", old)
    assert auth.needs_rehash(old)
    assert auth.needs_rehash("kapot")


def test_login_upgrades_old_hash(app, client):
    old = _oude_hash(ADMIN_PASSWORD)
    with ensure_db(app)() as s:
        s.scalar(select(AdminUser)).password_hash = old
        s.commit()
    assert login(client, "verkeerd-wachtwoord").status_code == 401
    with ensure_db(app)() as s:
        assert s.scalar(select(AdminUser)).password_hash == old  # mislukte login: niets gewijzigd
    ok = login(client)
    assert ok.status_code == 303
    with ensure_db(app)() as s:
        new = s.scalar(select(AdminUser)).password_hash
    assert new != old and new.startswith("scrypt$65536$8$2$")
    assert auth.verify_password(ADMIN_PASSWORD, new)
    # De nieuwe sessie blijft geldig (vingerafdruk is van de nieuwe hash).
    assert client.get(V).status_code == 200
    # Tweede login herhaalt de upgrade niet.
    client.cookies.clear()
    assert login(client).status_code == 303
    with ensure_db(app)() as s:
        assert s.scalar(select(AdminUser)).password_hash == new


def test_password_min_length():
    with pytest.raises(auth.AuthError):
        auth.hash_password("kort")


def test_secret_key_generated_once_and_private(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path / "d")
    k1 = auth.resolve_secret_key(s)
    k2 = auth.resolve_secret_key(s)
    path = tmp_path / "d" / "secret_key"
    assert k1 == k2 and len(k1) >= 32
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_secret_key_from_env_not_written(tmp_path):
    from pydantic import SecretStr

    s = Settings(_env_file=None, data_dir=tmp_path / "d", secret_key=SecretStr("abc" * 20))
    assert auth.resolve_secret_key(s) == "abc" * 20
    assert not (tmp_path / "d" / "secret_key").exists()


def test_no_secrets_in_logs(app, client, token, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    login(client, "verkeerd-wachtwoord")
    login(client)
    client.get(V, headers={"Authorization": f"Bearer {token}"})
    client.get(V, headers={"Authorization": "Bearer wwt_fout"})
    client.post(V, json={})
    key = (tmp_path / "data" / "secret_key").read_text()
    for secret in (token, key, ADMIN_PASSWORD, "verkeerd-wachtwoord", "wwt_fout"):
        assert secret not in caplog.text


def test_defaults_are_safe(app, monkeypatch):
    monkeypatch.delenv("WISSELWEER_HOST", raising=False)
    assert Settings(_env_file=None).host == "127.0.0.1"
    assert app.debug is False
    assert Settings(_env_file=None).cookie_secure is False  # via env aan te zetten


# ------------------------------------------------------------------ CLI


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    from wisselweer import settings as st

    monkeypatch.setenv("WISSELWEER_DATA_DIR", str(tmp_path / "cli"))
    st.get_settings.cache_clear()
    yield tmp_path / "cli"
    st.get_settings.cache_clear()


def _stdin(monkeypatch, text):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def test_cli_admin_and_tokens(cli_env, monkeypatch, capsys, caplog):
    _stdin(monkeypatch, "een-lang-wachtwoord\n")
    assert cli.main(["create-admin", "--username", "roel", "--password-stdin"]) == 0
    _stdin(monkeypatch, "nog-een-wachtwoord\n")
    assert cli.main(["create-admin", "--username", "ander", "--password-stdin"]) == 1
    _stdin(monkeypatch, "kort\n")
    assert cli.main(["reset-password", "--username", "roel", "--password-stdin"]) == 1
    _stdin(monkeypatch, "tweede-wachtwoord\n")
    assert cli.main(["reset-password", "--username", "roel", "--password-stdin"]) == 0
    capsys.readouterr()
    assert cli.main(["create-api-token", "--name", "ha"]) == 0
    out = capsys.readouterr().out
    token = re.search(r"wwt_\S+", out).group(0)
    assert cli.main(["create-api-token", "--name", "ha"]) == 1  # al actief
    assert cli.main(["revoke-api-token", "--name", "ha"]) == 0
    assert cli.main(["revoke-api-token", "--name", "ha"]) == 1
    from wisselweer.storage.db import session_scope

    with session_scope() as s:
        row = s.scalar(select(ApiToken))
        assert token not in row.token_hash and row.revoked_at is not None
        assert row.revoked_at <= datetime.now(UTC)
    assert "tweede-wachtwoord" not in caplog.text


def test_cli_has_no_password_argument():
    with pytest.raises(SystemExit):
        cli.main(["create-admin", "--username", "x", "--password", "geheim-wachtwoord"])
