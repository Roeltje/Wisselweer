"""Geen coördinaten in logs: httpx/httpcore stil en query uit de uvicorn-accesslog."""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from tests.unit.weather.helpers import load
from wisselweer.logsetup import StripQueryFilter, configure_logging
from wisselweer.weather.metno import MetNoProvider
from wisselweer.weather.openmeteo import OpenMeteoProvider


@pytest.fixture
def herstel_loggers():
    access = logging.getLogger("uvicorn.access")
    niveaus = {n: logging.getLogger(n).level for n in ("httpx", "httpcore")}
    filters = list(access.filters)
    yield
    for n, lvl in niveaus.items():
        logging.getLogger(n).setLevel(lvl)
    access.filters[:] = filters


@respx.mock
@pytest.mark.parametrize("bron", ["metno", "openmeteo"])
def test_provider_fetch_logt_geen_coordinaten(caplog, herstel_loggers, bron):
    configure_logging("INFO")
    caplog.set_level(logging.INFO)
    if bron == "metno":
        respx.get("https://api.met.no/weatherapi/locationforecast/2.0/complete").respond(
            200, json=load("metno_complete.json")
        )
        MetNoProvider("garage@example.invalid", client=httpx.Client()).fetch(52.1234, 5.9876)
    else:
        respx.get("https://api.open-meteo.com/v1/forecast").respond(
            200, json=load("openmeteo_forecast.json")
        )
        OpenMeteoProvider(client=httpx.Client()).fetch(52.1234, 5.9876)
    tekst = caplog.text.lower()
    for verboden in ("lat=", "latitude=", "lon=", "longitude=", "52.1234", "5.9876"):
        assert verboden not in tekst


def test_configure_logging_zet_httpx_en_httpcore_op_warning(herstel_loggers):
    logging.getLogger("httpx").setLevel(logging.DEBUG)
    logging.getLogger("httpcore").setLevel(logging.DEBUG)
    configure_logging("DEBUG")
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_configure_logging_is_idempotent_voor_accessfilter(herstel_loggers):
    configure_logging("INFO")
    configure_logging("INFO")
    access = logging.getLogger("uvicorn.access")
    assert sum(isinstance(f, StripQueryFilter) for f in access.filters) == 1


def test_accesslog_filter_haalt_query_uit_pad():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("192.0.2.1:5000", "GET", "/api/v1/advice?latitude=52.1&longitude=5.9", "1.1", 200),
        None,
    )
    assert StripQueryFilter().filter(record) is True
    tekst = record.getMessage()
    assert "/api/v1/advice " in tekst and "?" not in tekst
    assert "52.1" not in tekst and "200" in tekst
