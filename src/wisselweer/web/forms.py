"""Formulierhulpen: veldspecificaties, parsing en validatiefouten (alles server-side)."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, TypeVar

from fastapi import Request
from pydantic import ValidationError
from starlette.datastructures import FormData, UploadFile

E = TypeVar("E", bound=Enum)
Translate = Callable[..., str]


@dataclass(frozen=True)
class Field:
    """Eén formulierveld. `label` en `help` zijn i18n-sleutels."""

    name: str
    label: str
    kind: str = "text"
    required: bool = False
    help: str | None = None
    options: tuple[tuple[str, str], ...] = ()  # (waarde, zichtbare tekst)
    attrs: dict[str, str] = field(default_factory=dict)
    value: str = ""
    error: str | None = None
    # Extra CSS-klasse(n) op de omhullende `.field` en (bij een checkbox) de naam van een icoon.
    wrapper_class: str = ""
    icon: str = ""


def bind(fields: Iterable[Field], values: dict[str, str], errors: dict[str, str]) -> list[Field]:
    return [replace(f, value=values.get(f.name, f.value), error=errors.get(f.name)) for f in fields]


class Form:
    """Dunne wrapper om de ontvangen formulierwaarden."""

    def __init__(self, data: FormData) -> None:
        self._items: dict[str, list[str]] = {}
        for k, v in data.multi_items():
            if isinstance(v, str):
                self._items.setdefault(k, []).append(v)

    def get(self, name: str) -> str:
        vals = self._items.get(name)
        return vals[0].strip() if vals else ""

    def getlist(self, name: str) -> list[str]:
        return [v.strip() for v in self._items.get(name, [])]

    def values(self) -> dict[str, str]:
        """Eerste waarde per veld (om het formulier opnieuw te vullen)."""
        return {k: v[0] for k, v in self._items.items() if k != "csrf_token"}


async def read_form(request: Request) -> Form:
    return Form(await request.form())


async def read_upload(request: Request, name: str, limit: int) -> bytes | None:
    """Inhoud van het bestandsveld `name`, hooguit `limit + 1` bytes (zodat te groot te zien is).

    None als er geen bestand is gekozen. De bestandsnaam en het Content-Type van de browser worden
    bewust niet gebruikt.
    """
    item = (await request.form()).get(name)
    if not isinstance(item, UploadFile):
        return None
    return await item.read(limit + 1) or None


class Parser:
    """Verzamelt veldfouten tijdens het parsen van een Form."""

    def __init__(self, form: Form, tr: Translate) -> None:
        self.form = form
        self.tr = tr
        self.errors: dict[str, str] = {}

    def fail(self, name: str, key: str = "error.invalid", **params: Any) -> None:
        self.errors.setdefault(name, self.tr(key, **params))

    def text(self, name: str, *, required: bool = False, max_len: int = 255) -> str | None:
        v = self.form.get(name)
        if not v:
            if required:
                self.fail(name, "error.required")
            return None
        if len(v) > max_len:
            self.fail(name, "error.too_long", max=max_len)
            return None
        return v

    def integer(
        self,
        name: str,
        *,
        required: bool = False,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int | None:
        v = self.form.get(name)
        if not v:
            if required:
                self.fail(name, "error.required")
            return None
        try:
            n = int(v.replace(".", "").replace(" ", ""))
        except ValueError:
            self.fail(name, "error.number")
            return None
        if (minimum is not None and n < minimum) or (maximum is not None and n > maximum):
            self.fail(name, "error.range")
            return None
        return n

    def decimal(
        self,
        name: str,
        *,
        required: bool = False,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float | None:
        v = self.form.get(name)
        if not v:
            if required:
                self.fail(name, "error.required")
            return None
        try:
            n = float(Decimal(v.replace(",", ".")))
        except (InvalidOperation, ValueError):
            self.fail(name, "error.number")
            return None
        if n != n or n in (float("inf"), float("-inf")):
            self.fail(name, "error.number")
            return None
        if (minimum is not None and n < minimum) or (maximum is not None and n > maximum):
            self.fail(name, "error.range")
            return None
        return n

    def cents(self, name: str) -> int | None:
        v = self.decimal(name, minimum=0, maximum=10_000_000)
        return None if v is None else int(round(v * 100))

    def date(self, name: str, *, required: bool = False) -> date | None:
        v = self.form.get(name)
        if not v:
            if required:
                self.fail(name, "error.required")
            return None
        try:
            return date.fromisoformat(v)
        except ValueError:
            self.fail(name, "error.date")
            return None

    def choice(self, name: str, enum: type[E], *, required: bool = True) -> E | None:
        v = self.form.get(name)
        if not v:
            if required:
                self.fail(name, "error.required")
            return None
        try:
            return enum(v)
        except ValueError:
            self.fail(name, "error.invalid")
            return None

    def optional_id(self, name: str) -> int | None:
        v = self.form.get(name)
        if not v:
            return None
        if not v.isdigit() or len(v) > 9:
            self.fail(name, "error.invalid")
            return None
        return int(v)

    def apply_validation_error(self, exc: ValidationError, known: Iterable[str]) -> list[str]:
        """Zet pydantic-fouten om naar veldfouten; geeft overige meldingen terug."""
        known_set = set(known)
        rest: list[str] = []
        for err in exc.errors():
            loc = [str(p) for p in err["loc"]]
            name = next((p for p in loc if p in known_set), None)
            if name is not None:
                self.fail(name, "error.invalid")
            else:
                rest.append(self.tr("error.invalid"))
        return rest


_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def parse_time(v: str) -> time | None:
    m = _TIME_RE.match(v.strip())
    return time(int(m.group(1)), int(m.group(2))) if m else None


def parse_local_datetime(v: str) -> datetime | None:
    try:
        return datetime.fromisoformat(v.strip())
    except ValueError:
        return None
