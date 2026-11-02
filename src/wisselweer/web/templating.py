"""Centrale Jinja2-omgeving (autoescape aan) voor de webinterface."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import jinja2
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

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


templates.env.globals["t"] = _t
templates.env.filters["d"] = _date
templates.env.filters["dt"] = _datetime
templates.env.filters["km"] = _km
templates.env.filters["euro"] = _euro
