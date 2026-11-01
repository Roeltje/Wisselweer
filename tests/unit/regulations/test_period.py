from __future__ import annotations

from datetime import date

from wisselweer.regulations.models import Period
from wisselweer.regulations.period import in_period, period_label_nl

WRAP = Period(start_month=11, start_day=15, end_month=4, end_day=15)
YEAR_END = Period(start_month=12, start_day=1, end_month=3, end_day=31)
NO_WRAP = Period(start_month=3, start_day=1, end_month=10, end_day=31)


def test_wrap_boundaries_inclusive():
    assert in_period(WRAP, date(2026, 11, 15))
    assert not in_period(WRAP, date(2026, 11, 14))
    assert in_period(WRAP, date(2027, 1, 1))
    assert in_period(WRAP, date(2027, 4, 15))
    assert not in_period(WRAP, date(2027, 4, 16))
    assert not in_period(WRAP, date(2027, 7, 1))


def test_wrap_year_end():
    assert in_period(YEAR_END, date(2026, 12, 31))
    assert in_period(YEAR_END, date(2027, 1, 1))
    assert not in_period(YEAR_END, date(2026, 11, 30))


def test_no_wrap():
    assert in_period(NO_WRAP, date(2026, 6, 1))
    assert in_period(NO_WRAP, date(2026, 3, 1)) and in_period(NO_WRAP, date(2026, 10, 31))
    assert not in_period(NO_WRAP, date(2026, 2, 28)) and not in_period(NO_WRAP, date(2026, 11, 1))


def test_label():
    p = Period(start_month=11, start_day=1, end_month=4, end_day=15)
    assert period_label_nl(p) == "1 november – 15 april"
