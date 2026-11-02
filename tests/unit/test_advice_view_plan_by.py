"""De afspraakregel in de weergave: geen 'vóór <vandaag>' (dat kan niet meer)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from wisselweer.core.models import Advice, AdviceStatus, Direction
from wisselweer.web.views import build_advice_view

TZ = ZoneInfo("Europe/Amsterdam")


def _view(plan_by):
    today = datetime.now(TZ).date()
    advice = Advice(
        direction=Direction.TO_WINTER,
        heading="heading.to_winter.prepare_change",
        status=AdviceStatus.PREPARE_CHANGE,
        recommended_period=(today + timedelta(days=3), today + timedelta(days=8)),
        plan_appointment_by=plan_by,
        evaluated_at=datetime.now(UTC),
    )
    return build_advice_view(advice, "nl-NL", TZ, [], no_mounted=False)


def test_plan_by_today_or_earlier_says_as_soon_as_possible():
    today = datetime.now(TZ).date()
    for day in (today, today - timedelta(days=1)):
        assert _view(day).plan_by == "Plan zo snel mogelijk een afspraak"


def test_plan_by_in_future_shows_the_date():
    text = _view(datetime.now(TZ).date() + timedelta(days=2)).plan_by
    assert text.startswith("Plan een afspraak vóór ")
