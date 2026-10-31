from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from tests.unit.core.helpers import AUTUMN_NOW, Day, forecast, repeat, run
from wisselweer.core import AdviceStatus, Forecast, TireType, WarningCode

MILD = Day(8, 15)
COLD = Day(1, 6)
FIX = Path(__file__).parents[2] / "fixtures" / "weather"


def keys(items):
    return [r.key for r in items]


def test_missing_variables_become_uncertainties_not_guesses():
    a = run([MILD, Day(-3, 2), *repeat(MILD, 12)], drop=("dew_point_c", "snow_cm"))
    missing = {
        r.params["variable"] for r in a.uncertainties if r.key == "uncertainty.missing_variable"
    }
    assert {"dew_point_c", "snow_cm"} <= missing
    assert "humidity_pct" not in missing
    # geen verzonnen sneeuwwaarschuwing
    assert WarningCode.POSSIBLE_SNOW not in {w.code for w in a.warnings}


def test_all_variables_present_no_missing_uncertainty():
    a = run(repeat(MILD, 14))
    assert not [r for r in a.uncertainties if r.key == "uncertainty.missing_variable"]


def test_stale_forecast_warns_but_still_advises():
    a = run(repeat(COLD, 14), is_stale=True)
    assert WarningCode.FORECAST_STALE in {w.code for w in a.warnings}
    assert a.status == AdviceStatus.CHANGE_RECOMMENDED
    assert "uncertainty.forecast_stale" in keys(a.uncertainties)


def test_too_old_forecast_is_insufficient():
    fc = forecast(repeat(COLD, 14), fetched_at=AUTUMN_NOW - timedelta(hours=48))
    a = run(None, fc=fc)
    assert a.status == AdviceStatus.INSUFFICIENT_DATA
    assert WarningCode.FORECAST_STALE in {w.code for w in a.warnings}
    assert a.recommended_date is None


def test_no_forecast_is_insufficient():
    a = run(None)
    assert a.status == AdviceStatus.INSUFFICIENT_DATA
    assert [w.code for w in a.warnings] == [WarningCode.FORECAST_UNAVAILABLE]
    assert a.forecast_provider is None


def test_too_few_hours_is_insufficient():
    fc = forecast([MILD])  # alleen vandaag, deels in het verleden
    fc = fc.model_copy(update={"hourly": fc.hourly[:10]})
    a = run(None, fc=fc)
    assert a.status == AdviceStatus.INSUFFICIENT_DATA
    assert WarningCode.FORECAST_UNAVAILABLE in {w.code for w in a.warnings}


def test_no_temperature_at_all_is_insufficient():
    a = run(repeat(MILD, 14), drop=("temperature_c",))
    assert a.status == AdviceStatus.INSUFFICIENT_DATA


def test_output_has_no_percentages():
    a = run([MILD, Day(-3, 2), *repeat(MILD, 12)])
    dumped = json.dumps(a.model_dump(mode="json"))
    assert "%" not in dumped and "percent" not in dumped and "probab" not in dumped


def test_advice_is_json_roundtrippable():
    from wisselweer.core import Advice

    a = run([MILD, MILD, *repeat(COLD, 12)])
    assert Advice.model_validate_json(a.model_dump_json()) == a


def test_json_fixtures_evaluate():
    mild = Forecast.model_validate_json((FIX / "mild_autumn.json").read_text())
    snap = Forecast.model_validate_json((FIX / "cold_snap.json").read_text())
    frost = Forecast.model_validate_json((FIX / "persistent_frost.json").read_text())
    kw = dict(now=AUTUMN_NOW)
    assert (
        run(None, fc=mild.model_copy(update={"fetched_at": AUTUMN_NOW}), **kw).status
        == AdviceStatus.KEEP_CURRENT
    )
    a = run(None, fc=snap.model_copy(update={"fetched_at": AUTUMN_NOW}), **kw)
    assert a.status == AdviceStatus.CHANGE_RECOMMENDED
    b = run(None, TireType.SUMMER, fc=frost.model_copy(update={"fetched_at": AUTUMN_NOW}), **kw)
    assert b.status == AdviceStatus.CHANGE_RECOMMENDED
    assert WarningCode.POSSIBLE_FROST in {w.code for w in b.warnings}
