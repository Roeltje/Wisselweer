"""DOT-code: productieweek, -jaar en leeftijd."""

from __future__ import annotations

from datetime import date

import pytest

from wisselweer.tires.dot import age_years, dot_age_years, production_date

TODAY = date(2026, 11, 1)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("2319", date(2019, 6, 3)),  # week 23 van 2019: maandag 3 juni
        ("DOT 4KXH 123 2319", date(2019, 6, 3)),
        ("  dot xx 2319  ", date(2019, 6, 3)),
        ("2319.", date(2019, 6, 3)),  # leesteken erachter
        ("DOT B3K9 2319 N", date(2019, 6, 3)),  # letters na de vier cijfers
        ("0120", date(2019, 12, 30)),  # ISO-week 1 van 2020 begint al op 30 december 2019
        ("5223", date(2023, 12, 25)),
        ("1222", date(2022, 3, 21)),
    ],
)
def test_geldige_codes(code, expected):
    assert production_date(code, TODAY) == expected


def test_week_53_valt_op_maandag_na_week_52():
    # 2020 heeft 53 ISO-weken; 2021 heeft er 52: week 53 komt dan in de eerste week van 2022.
    assert production_date("5320", TODAY) == date(2020, 12, 28)
    assert production_date("5321", TODAY) == date(2022, 1, 3)


@pytest.mark.parametrize(
    "code",
    [
        None,
        "",
        "   ",
        "geen code",
        "123",  # drie cijfers (oude codes van vóór 2000)
        "DOT 239",
        "0019",  # week 0
        "5419",  # week 54
        "9919",
        "2319 1",  # cijfers na de vier cijfers: niet de laatste vier
        "23-19",
        "2 3 1 9",
        "4727",  # productiedatum in de toekomst (week 47 van 2027)
    ],
)
def test_ongeldige_codes_geven_geen_datum(code):
    assert production_date(code, TODAY) is None
    assert dot_age_years(code, TODAY) is None


def test_net_geproduceerd_is_geen_toekomst():
    # Week 44 van 2026 begint op 26 oktober: gisteren, dus geldig; leeftijd 0,0.
    assert production_date("4426", TODAY) == date(2026, 10, 26)
    assert dot_age_years("4426", TODAY) == 0.0
    # Een paar weken vooruit (voorraad die voor de datum is gemerkt) telt nog wel.
    assert production_date("4726", TODAY) == date(2026, 11, 16)


def test_leeftijd_in_jaren_een_decimaal():
    assert dot_age_years("2319", TODAY) == 7.4  # 3 juni 2019 -> 1 nov 2026
    assert dot_age_years("4416", date(2026, 10, 31)) == 10.0
    assert age_years(date(2020, 1, 1), date(2020, 1, 1)) == 0.0
    assert age_years(date(2020, 1, 1), date(2019, 1, 1)) == 0.0  # nooit negatief
    assert age_years(None, TODAY) is None


def test_jaar_2000_en_later():
    assert production_date("0100", date(2001, 1, 1)) == date(2000, 1, 3)
    assert production_date("1099", TODAY) is None  # 2099: toekomst
