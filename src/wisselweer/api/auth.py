"""Authenticatie: wachtwoorden, sessies, CSRF, API-tokens, login/logout en beveiligde docs.

Geheimen (wachtwoorden, tokens, secret key) worden nooit gelogd.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wisselweer.api.deps import ensure_db
from wisselweer.settings import Settings
from wisselweer.storage.orm import AdminUser, ApiToken
from wisselweer.web.templating import templates

log = logging.getLogger("wisselweer.auth")

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 1000
SESSION_COOKIE = "ww_session"
SESSION_MAX_AGE = 7 * 24 * 3600
TOKEN_PREFIX = "wwt_"
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 300
MUTATING_METHODS = {"POST", "PATCH", "PUT", "DELETE"}
LOGIN_ERROR = "Onjuiste gebruikersnaam of wachtwoord"

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _SALT_BYTES, _DKLEN = 2**14, 8, 1, 16, 32


class AuthError(ValueError):
    """Ongeldige invoer bij het beheren van gebruikers of tokens (bevat nooit geheimen)."""


# --------------------------------------------------------------------------- wachtwoorden


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen, maxmem=128 * 1024 * 1024
    )


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Wachtwoord moet minimaal {MIN_PASSWORD_LENGTH} tekens bevatten")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AuthError("Wachtwoord is te lang")


def hash_password(password: str) -> str:
    """`scrypt$n$r$p$salt_b64$hash_b64`; geen plaintext in het resultaat."""
    validate_password(password)
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _scrypt(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _DKLEN)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        actual = _scrypt(
            password, base64.b64decode(salt_b64), int(n), int(r), int(p), len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


_DUMMY_HASH = hash_password("dummy-password-for-timing")


# --------------------------------------------------------------------------- secret key


def resolve_secret_key(settings: Settings) -> str:
    """`WISSELWEER_SECRET_KEY`, anders een eenmalig gegenereerd bestand in `data_dir`."""
    if settings.secret_key is not None:
        return settings.secret_key.get_secret_value()
    path = Path(settings.data_dir) / "secret_key"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return key
        raise RuntimeError(f"{path} is leeg; verwijder het bestand") from None
    key = secrets.token_urlsafe(48)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(key)
    os.chmod(path, 0o600)
    return key


# --------------------------------------------------------------------------- beheer (CLI)


def _clean_username(username: str) -> str:
    username = username.strip()
    if not username or len(username) > 80:
        raise AuthError("Gebruikersnaam moet 1 tot 80 tekens bevatten")
    return username


def create_admin(session: Session, username: str, password: str) -> AdminUser:
    username = _clean_username(username)
    if session.scalar(select(func.count()).select_from(AdminUser)):
        raise AuthError("Er bestaat al een beheerder; gebruik reset-password")
    user = AdminUser(username=username, password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


def reset_password(session: Session, username: str, password: str) -> None:
    user = session.scalar(select(AdminUser).where(AdminUser.username == username.strip()))
    if user is None:
        raise AuthError("Gebruiker bestaat niet")
    user.password_hash = hash_password(password)
    session.flush()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_api_token(session: Session, name: str) -> str:
    """Geeft het token terug; alleen de SHA-256-hash wordt opgeslagen."""
    name = _clean_username(name)
    active = session.scalar(
        select(ApiToken).where(ApiToken.name == name, ApiToken.revoked_at.is_(None))
    )
    if active is not None:
        raise AuthError("Er bestaat al een actief token met deze naam")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    session.add(ApiToken(name=name, token_hash=hash_token(token)))
    session.flush()
    return token


def revoke_api_token(session: Session, name: str) -> int:
    rows = session.scalars(
        select(ApiToken).where(ApiToken.name == name.strip(), ApiToken.revoked_at.is_(None))
    ).all()
    if not rows:
        raise AuthError("Geen actief token met deze naam")
    now = datetime.now(UTC)
    for row in rows:
        row.revoked_at = now
    session.flush()
    return len(rows)


# --------------------------------------------------------------------------- sessie + CSRF


def get_csrf_token(request: Request) -> str:
    """CSRF-token van de sessie (wordt aangemaakt als het ontbreekt)."""
    token = request.session.get("csrf")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def _password_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def start_session(request: Request, user: AdminUser) -> None:
    """Nieuwe sessie na login; oude sessiedata (incl. CSRF-token) wordt gewist."""
    request.session.clear()
    request.session.update(
        {
            "uid": user.id,
            "pv": _password_fingerprint(user.password_hash),
            "csrf": secrets.token_urlsafe(32),
            "created": int(time.time()),
        }
    )


def safe_next(value: str | None) -> str:
    """Alleen relatieve, same-site paden; anders `/`."""
    if not value or not value.startswith("/") or value.startswith(("//", "/\\")):
        return "/"
    if any(ord(c) < 32 or c in "\\" for c in value) or value.startswith("/login"):
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return "/"
    return value


@dataclass(frozen=True)
class Principal:
    kind: Literal["session", "token"]
    user_id: int | None = None
    token_name: str | None = None


class LoginRequired(Exception):
    """HTML-route zonder sessie: wordt een redirect naar /login."""


def _factory(request: Request):
    return ensure_db(request.app)


def _token_principal(request: Request, token: str) -> Principal | None:
    if not token.startswith(TOKEN_PREFIX):
        return None
    with _factory(request)() as db:
        row = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(token)))
        if row is None or row.revoked_at is not None:
            return None
        now = datetime.now(UTC)
        if row.last_used_at is None or now - row.last_used_at > timedelta(minutes=1):
            row.last_used_at = now
            db.commit()
        return Principal("token", token_name=row.name)


def _session_principal(request: Request) -> Principal | None:
    data = request.session
    uid, created = data.get("uid"), data.get("created")
    if not isinstance(uid, int) or not isinstance(created, int):
        return None
    if time.time() - created > SESSION_MAX_AGE:
        return None
    with _factory(request)() as db:
        user = db.get(AdminUser, uid)
        if user is None:
            return None
        # Wachtwoordwijziging maakt bestaande sessies ongeldig.
        if not hmac.compare_digest(
            str(data.get("pv", "")), _password_fingerprint(user.password_hash)
        ):
            return None
    return Principal("session", user_id=uid)


async def _csrf_ok(request: Request) -> bool:
    expected = request.session.get("csrf")
    if not isinstance(expected, str) or not expected:
        return False
    supplied = request.headers.get("x-csrf-token")
    if supplied is None:
        ctype = request.headers.get("content-type", "")
        if ctype.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            value = (await request.form()).get("csrf_token")
            supplied = value if isinstance(value, str) else None
    if supplied is None:
        return False
    return secrets.compare_digest(supplied.encode(), expected.encode())


async def _authenticate(request: Request) -> Principal | None:
    header = request.headers.get("authorization", "")
    if header:
        scheme, _, token = header.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return _token_principal(request, token.strip())
        return None
    principal = _session_principal(request)
    if principal is None:
        return None
    if request.method in MUTATING_METHODS and not await _csrf_ok(request):
        log.warning("csrf_failed path=%s", request.url.path)
        raise HTTPException(status_code=403, detail="csrf_failed")
    return principal


async def require_user(request: Request) -> Principal:
    """API-dependency: sessie (+CSRF bij muterende methodes) of Bearer-token, anders 401."""
    principal = await _authenticate(request)
    if principal is None:
        raise HTTPException(
            status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"}
        )
    return principal


async def require_user_html(request: Request) -> Principal:
    """HTML-dependency: zonder sessie een redirect naar `/login?next=...`."""
    principal = await _authenticate(request)
    if principal is None or principal.kind != "session":
        raise LoginRequired
    return principal


CurrentUser = Annotated[Principal, Depends(require_user)]
CurrentUserHtml = Annotated[Principal, Depends(require_user_html)]


# --------------------------------------------------------------------------- rate limit


class LoginRateLimiter:
    """Mislukte inlogpogingen per IP, in geheugen (5 per 5 minuten)."""

    def __init__(
        self, max_failures: int = LOGIN_MAX_FAILURES, window: int = LOGIN_WINDOW_SECONDS
    ) -> None:
        self.max_failures = max_failures
        self.window = window
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._failures.setdefault(key, deque())
        while q and now - q[0] > self.window:
            q.popleft()
        if not q:
            self._failures.pop(key, None)
        return q

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key, time.monotonic())) >= self.max_failures

    def fail(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(key, now)
            self._failures.setdefault(key, deque()).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# --------------------------------------------------------------------------- routes

router = APIRouter(include_in_schema=False)

DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'; base-uri 'none'"
)


def _render_login(
    request: Request, *, error: str | None = None, next_path: str = "/", status: int = 200
) -> Response:
    with _factory(request)() as db:
        no_admin = not db.scalar(select(func.count()).select_from(AdminUser))
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": error, "next": next_path, "no_admin": no_admin},
        status_code=status,
    )


@router.get("/login")
async def login_form(request: Request, next: str = "/") -> Response:
    if _session_principal(request) is not None:
        return RedirectResponse(safe_next(next), status_code=303)
    return _render_login(request, next_path=safe_next(next))


@router.post("/login")
async def login_submit(
    request: Request,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "/",
) -> Response:
    next_path = safe_next(next)
    expected = request.session.get("csrf")
    if not isinstance(expected, str) or not secrets.compare_digest(
        csrf_token.encode(), expected.encode()
    ):
        return JSONResponse(status_code=403, content={"detail": "csrf_failed"})
    limiter: LoginRateLimiter = request.app.state.login_limiter
    ip = _client_ip(request)
    if limiter.blocked(ip):
        log.warning("login_rate_limited")
        return _render_login(
            request,
            error="Te veel mislukte pogingen; probeer het later opnieuw",
            next_path=next_path,
            status=429,
        )
    user = None
    with _factory(request)() as db:
        if 0 < len(password) <= MAX_PASSWORD_LENGTH:
            user = db.scalar(select(AdminUser).where(AdminUser.username == username.strip()))
            ok = verify_password(password, user.password_hash if user else _DUMMY_HASH)
            if not ok or user is None:
                user = None
    if user is None:
        limiter.fail(ip)
        log.warning("login_failed")
        return _render_login(request, error=LOGIN_ERROR, next_path=next_path, status=401)
    limiter.reset(ip)
    start_session(request, user)
    return RedirectResponse(next_path, status_code=303)


@router.post("/logout")
async def logout(request: Request) -> Response:
    if _session_principal(request) is not None and not await _csrf_ok(request):
        return JSONResponse(status_code=403, content={"detail": "csrf_failed"})
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/openapi.json", dependencies=[Depends(require_user)])
async def openapi_json(request: Request) -> JSONResponse:
    return JSONResponse(request.app.openapi())


@router.get("/docs", dependencies=[Depends(require_user_html)])
async def swagger_docs() -> HTMLResponse:
    html = get_swagger_ui_html(openapi_url="/openapi.json", title="Wisselweer API")
    html.headers["Content-Security-Policy"] = DOCS_CSP
    return html


async def _login_redirect(request: Request, exc: Exception) -> Response:
    target = request.url.path
    if request.method == "GET" and request.url.query:
        target += "?" + request.url.query
    return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)


def install_auth(app: FastAPI, settings: Settings) -> None:
    """Hangt sessies, login/logout, beveiligde docs en de rate limiter aan de app."""
    from starlette.middleware.sessions import SessionMiddleware

    app.state.login_limiter = LoginRateLimiter()
    app.add_exception_handler(LoginRequired, _login_redirect)
    app.add_middleware(
        SessionMiddleware,
        secret_key=resolve_secret_key(settings),
        session_cookie=SESSION_COOKIE,
        max_age=SESSION_MAX_AGE,
        same_site="strict",
        https_only=settings.cookie_secure,
    )
    app.include_router(router)
