"""Adres/plaats -> coördinaten (geocoderen) onder /api/v1/geocode."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import StringConstraints

from wisselweer.api.deps import get_geocoder
from wisselweer.geocoding import (
    MAX_QUERY_CHARS,
    MIN_QUERY_CHARS,
    Geocoder,
    GeocodeResult,
    GeocoderNotConfigured,
    GeocoderRateLimited,
    GeocoderUnavailable,
)
from wisselweer.i18n import SUPPORTED_LOCALES, normalize_locale

log = logging.getLogger("wisselweer.api")

router = APIRouter(prefix="/api/v1")

GeocoderDep = Annotated[Geocoder, Depends(get_geocoder)]
SearchText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=MIN_QUERY_CHARS, max_length=MAX_QUERY_CHARS
    ),
]


def _locale(request: Request, lang: str | None) -> str:
    """Taal voor de resultaten: `lang`, anders de taal van de sessie, anders de standaardtaal."""
    if lang in SUPPORTED_LOCALES:
        return lang
    return normalize_locale(request.session.get("lang"))


@router.get("/geocode", response_model=list[GeocodeResult])
def geocode(
    request: Request,
    geocoder: GeocoderDep,
    q: Annotated[SearchText, Query()],
    lang: Annotated[str | None, Query(max_length=8)] = None,
) -> list[GeocodeResult]:
    """Zoekt tot 5 locaties bij een adres, postcode of plaats; coördinaten op 3 decimalen.

    De zoektekst wordt bewust niet gelogd.
    """
    try:
        return geocoder.search(q, _locale(request, lang))
    except GeocoderNotConfigured:
        raise HTTPException(status_code=503, detail="geocoder_not_configured") from None
    except GeocoderRateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail="geocoder_rate_limited",
            headers={"Retry-After": str(max(1, round(exc.retry_after_s)))},
        ) from None
    except GeocoderUnavailable:
        log.warning("geocoder_unavailable")
        raise HTTPException(status_code=502, detail="geocoder_unavailable") from None
