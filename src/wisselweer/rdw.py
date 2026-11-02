"""Kenteken -> voertuiggegevens en openstaande terugroepacties via RDW Open Data (Socrata).

Openbare data zonder API-key. Alleen een genormaliseerd Nederlands kenteken (letters en cijfers)
gaat naar de RDW, en alleen als de gebruiker daar zelf om vraagt. Het kenteken wordt niet gelogd
en foutmeldingen bevatten geen URL of kenteken.

Datasets:
- m9d7-ebf2  Gekentekende voertuigen (merk, handelsbenaming, datum eerste toelating, indicator
             openstaande terugroepactie)
- t49b-isb7  Terugroep_actie_status per kenteken (code O = openstaand, P = herstel gemeld)
- j9yg-7rg9  Terugroep_actie: omschrijving van het defect en het herstel per referentiecode
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

import httpx
from pydantic import BaseModel

from wisselweer.weather._util import http_get, make_client, quiet_httpx_logging
from wisselweer.weather.base import ProviderRateLimited, ProviderUnavailable

PROVIDER = "rdw"
DEFAULT_RDW_URL = "https://opendata.rdw.nl"
VEHICLES = "m9d7-ebf2"
RECALL_STATUS = "t49b-isb7"
RECALLS = "j9yg-7rg9"
MAX_RECALLS = 5
MAX_TEXT = 1000
CACHE_TTL_S = 6 * 3600.0
CACHE_MAX_ITEMS = 200
_PLATE_RE = re.compile(r"^[A-Z0-9]{4,8}$")
_REF_RE = re.compile(r"^[A-Z0-9]{3,20}$")


class Recall(BaseModel):
    reference: str
    defect: str | None = None
    remedy: str | None = None
    published: str | None = None  # ISO-datum (JJJJ-MM-DD)


class RdwVehicle(BaseModel):
    plate: str
    make: str | None = None
    model: str | None = None
    build_year: int | None = None
    color: str | None = None
    open_recall: bool | None = None
    recalls: list[Recall] = []


class RdwError(Exception):
    """Basisfout; de boodschap bevat nooit het kenteken of een URL."""


class RdwDisabled(RdwError):
    """De RDW-koppeling staat uit."""


class RdwUnavailable(RdwError):
    """Netwerkfout, time-out of onbruikbaar antwoord van de RDW."""


class RdwNotFound(RdwError):
    """Geen voertuig met dit kenteken in de open data."""


def normalize_plate(value: str) -> str | None:
    """'ab-123-c' -> 'AB123C'. None als het geen bruikbaar Nederlands kenteken kan zijn."""
    plate = re.sub(r"[\s\-.]", "", value or "").upper()
    return plate if _PLATE_RE.match(plate) else None


def _text(value: object, limit: int = MAX_TEXT) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    if not value or value.lower() in ("niet geregistreerd", "(nog) niet bekend"):
        return None
    return value[:limit]


def _title(value: str | None) -> str | None:
    """RDW levert hoofdletters ('VOLKSWAGEN', 'GOLF VARIANT'); netjes voor in het formulier.

    Korte afkortingen (BMW, GTI, ID.3) blijven in hoofdletters.
    """
    if value is None:
        return None
    words = []
    for w in value.split(" "):
        if len(w) <= 3 or any(c.isdigit() for c in w):
            words.append(w)
        else:
            words.append("-".join(part.capitalize() for part in w.split("-")))
    return " ".join(words)


def _date(value: object) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return None


def parse_vehicle(plate: str, rows: object) -> RdwVehicle:
    if not isinstance(rows, list):
        raise RdwUnavailable("onverwacht antwoordformaat")
    row = next((r for r in rows if isinstance(r, dict)), None)
    if row is None:
        raise RdwNotFound("onbekend kenteken")
    first = _date(row.get("datum_eerste_toelating"))
    indicator = row.get("openstaande_terugroepactie_indicator")
    return RdwVehicle(
        plate=plate,
        make=_title(_text(row.get("merk"), 80)),
        model=_title(_text(row.get("handelsbenaming"), 80)),
        build_year=int(first[:4]) if first else None,
        color=_text(row.get("eerste_kleur"), 40),
        open_recall={"Ja": True, "Nee": False}.get(indicator)
        if isinstance(indicator, str)
        else None,
    )


def parse_open_references(rows: object) -> list[str]:
    if not isinstance(rows, list):
        raise RdwUnavailable("onverwacht antwoordformaat")
    refs: list[str] = []
    for r in rows:
        if not isinstance(r, dict) or r.get("code_status") != "O":
            continue
        ref = r.get("referentiecode_rdw")
        if isinstance(ref, str) and _REF_RE.match(ref) and ref not in refs:
            refs.append(ref)
    return refs[:MAX_RECALLS]


def parse_recalls(refs: list[str], rows: object) -> list[Recall]:
    if not isinstance(rows, list):
        raise RdwUnavailable("onverwacht antwoordformaat")
    by_ref = {r.get("referentiecode_rdw"): r for r in rows if isinstance(r, dict)}
    out = []
    for ref in refs:
        r = by_ref.get(ref, {})
        out.append(
            Recall(
                reference=ref,
                defect=_text(r.get("omschrijving_defect")),
                remedy=_text(r.get("beschrijving_van_het_herstel")),
                published=_date(r.get("publicatiedatum_rdw")),
            )
        )
    return out


def _now() -> float:
    return time.monotonic()


class RdwClient:
    def __init__(
        self,
        base_url: str,
        client: httpx.Client | None = None,
        *,
        clock: Callable[[], float] = _now,
    ) -> None:
        self._base_url = base_url.strip().rstrip("/")
        self._client = make_client(client)
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[float, RdwVehicle]] = OrderedDict()
        quiet_httpx_logging()  # het kenteken staat in de query-string

    @property
    def enabled(self) -> bool:
        return bool(self._base_url)

    def _get(self, dataset: str, params: dict[str, object]) -> object:
        try:
            resp = http_get(
                self._client,
                f"{self._base_url}/resource/{dataset}.json",
                provider=PROVIDER,
                params=params,
                headers={"Accept": "application/json"},
            )
            return resp.json()
        except (ProviderUnavailable, ProviderRateLimited):
            raise RdwUnavailable("rdw niet bereikbaar") from None
        except ValueError:
            raise RdwUnavailable("ongeldige JSON") from None

    def lookup(self, plate: str) -> RdwVehicle:
        """`plate` moet al genormaliseerd zijn (zie `normalize_plate`)."""
        if not self.enabled:
            raise RdwDisabled("rdw staat uit")
        cached = self._cache_get(plate)
        if cached is not None:
            return cached
        vehicle = parse_vehicle(plate, self._get(VEHICLES, {"kenteken": plate, "$limit": 1}))
        if vehicle.open_recall:
            refs = parse_open_references(
                self._get(RECALL_STATUS, {"kenteken": plate, "code_status": "O", "$limit": 20})
            )
            if refs:
                quoted = ",".join(f"'{r}'" for r in refs)  # refs zijn gevalideerd (A-Z0-9)
                rows = self._get(
                    RECALLS, {"$where": f"referentiecode_rdw in ({quoted})", "$limit": MAX_RECALLS}
                )
                vehicle.recalls = parse_recalls(refs, rows)
        self._cache_put(plate, vehicle)
        return vehicle

    def _cache_get(self, key: str) -> RdwVehicle | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            expires, value = entry
            if self._clock() >= expires:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return value.model_copy(deep=True)

    def _cache_put(self, key: str, value: RdwVehicle) -> None:
        with self._lock:
            self._cache[key] = (self._clock() + CACHE_TTL_S, value.model_copy(deep=True))
            self._cache.move_to_end(key)
            while len(self._cache) > CACHE_MAX_ITEMS:
                self._cache.popitem(last=False)
