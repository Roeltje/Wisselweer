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
