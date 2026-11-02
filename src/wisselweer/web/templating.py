"""Centrale Jinja2-omgeving (autoescape aan) voor de webinterface."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import jinja2
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from markupsafe import Markup, escape

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
# Starlette zet autoescape standaard aan; hier expliciet vastgelegd.
templates.env.autoescape = jinja2.select_autoescape(
    enabled_extensions=("html", "htm", "xml"), default_for_string=True, default=True
)


@pass_context
def _csrf_token(context: dict[str, Any]) -> str:
    from wisselweer.api.auth import get_csrf_token

    return get_csrf_token(context["request"])


templates.env.globals["csrf_token"] = _csrf_token


def _static_version() -> str:
    """Korte hash van alle statische bestanden, als `?v=` tegen verouderde browsercaches.

    Wordt eenmalig bij opstart bepaald; verandert bij elke wijziging van een bestand.
    """
    digest = hashlib.sha256()
    for path in sorted(STATIC_DIR.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(STATIC_DIR).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


templates.env.globals["static_v"] = _static_version()


# --- i18n en opmaak ------------------------------------------------------------------------


def _locale(context: Any) -> str:
    from wisselweer.i18n import DEFAULT_LOCALE

    return context.get("locale") or DEFAULT_LOCALE


@pass_context
def _t(context: Any, key: str, **params: Any) -> str:
    from wisselweer.i18n import t

    return t(key, _locale(context), **params)


@pass_context
def _date(context: Any, value: Any) -> str:
    from wisselweer.i18n import format_date

    return format_date(value, _locale(context))


@pass_context
def _datetime(context: Any, value: Any) -> str:
    from wisselweer.i18n import format_datetime

    return format_datetime(value, _locale(context))


@pass_context
def _km(context: Any, value: int | None) -> str:
    from wisselweer.i18n import format_number

    return "" if value is None else format_number(value, _locale(context))


@pass_context
def _euro(context: Any, cents: int | None) -> str:
    from wisselweer.i18n import format_euro

    return format_euro(cents, _locale(context))


def locale_context(locale: str) -> dict[str, Any]:
    """Gegevens voor de taalkiezer in de footer (taalnamen staan in de eigen taal)."""
    from wisselweer.i18n import LOCALE_NAMES, SUPPORTED_LOCALES

    return {"locale": locale, "locales": SUPPORTED_LOCALES, "locale_names": LOCALE_NAMES}


# Bandsymbolen in lopende tekst: achter "3PMSF" en "M+S" volgt het symbool zelf (zelfde tekening als
# branding/icons). Decoratief (aria-hidden): de tekst noemt het symbool al.
_MARK_SVG = {
    "3PMSF": (
        '<svg class="mark-inline" viewBox="0 0 64 64" fill="none" stroke="currentColor" '
        'stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" '
        'focusable="false"><path d="M4 56l10-30 7 10 11-26 11 26 7-10 10 30z"/>'
        '<path stroke-width="3.2" d="M32 36.5v17M24.6 40.75l14.8 8.5M24.6 49.25l14.8-8.5"/></svg>'
    ),
    "M+S": (
        '<svg class="mark-inline" viewBox="0 0 64 64" fill="none" stroke="currentColor" '
        'stroke-width="3.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" '
        'focusable="false"><rect x="4" y="14" width="56" height="36" rx="9"/>'
        '<path d="M12 40V24l6.5 9L25 24v16M28.8 32h9.4M33.5 27.3v9.4M52 27c-1-2.5-3.5-3-5.5-3-3 0-5 '
        '1.8-5 4 0 2.5 2.3 3.3 5.3 4 3 .7 5.4 1.6 5.4 4.2 0 2.3-2.4 3.8-5.4 3.8-2.8 0-5-1-5.8-3.5"/>'
        "</svg>"
    ),
}
_MARK_RE = re.compile(r"(3PMSF|M\+S)(\S*)")


def _marks(value: Any) -> Markup:
    """Escapet de tekst en zet het symbool achter elke 3PMSF/M+S (met aangeplakt woorddeel, bv.
    "-symbool", op één regel)."""
    text = str(escape(value))
    return Markup(
        _MARK_RE.sub(
            lambda m: f'<span class="mark-keep">{m[1]}{_MARK_SVG[m[1]]}{m[2]}</span>', text
        )
    )


templates.env.globals["t"] = _t
templates.env.filters["marks"] = _marks
templates.env.filters["d"] = _date
templates.env.filters["dt"] = _datetime
templates.env.filters["km"] = _km
templates.env.filters["euro"] = _euro
