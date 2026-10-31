"""Centrale Jinja2-omgeving (autoescape aan) voor de webinterface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jinja2
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

TEMPLATE_DIR = Path(__file__).parent / "templates"

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


def _km(value: int | None) -> str:
    return "" if value is None else f"{value:,}".replace(",", ".")


def _euro(cents: int | None) -> str:
    if cents is None:
        return ""
    return "€ " + f"{cents / 100:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


templates.env.globals["t"] = _t
templates.env.filters["d"] = _date
templates.env.filters["dt"] = _datetime
templates.env.filters["km"] = _km
templates.env.filters["euro"] = _euro
