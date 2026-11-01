from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from tests.integration.web.conftest import (
    VEHICLE_FORM,
    FailingProvider,
    create_sets,
    create_vehicle,
)
from wisselweer.api.deps import apply_default_provider_setting, ensure_db
from wisselweer.storage.orm import (
    AppSetting,
    OdometerReading,
    TireChange,
    TireSet,
    Vehicle,
)
from wisselweer.weather.cache import ForecastCache, InMemoryBackend
from wisselweer.weather.service import ForecastService

STATIC_PAGES = ["/", "/garages", "/garages/new", "/settings", "/vehicles/new"]


def vehicle_pages(vid: int) -> list[str]:
    base = f"/vehicles/{vid}"
    return [
        base,
        f"{base}/edit",
        f"{base}/location",
        f"{base}/profile",
        f"{base}/method",
        f"{base}/delete",
        f"{base}/sets/new",
        f"{base}/changes/new",
    ]


@pytest.mark.parametrize("url", [*STATIC_PAGES, "/vehicles/1", "/vehicles/1/profile"])
def test_pages_redirect_to_login_without_session(anon, url):
    r = anon.get(url, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login?next=")


def test_static_assets_are_public(anon):
    for path, ctype in (
        ("/static/app.css", "text/css"),
        ("/static/app.js", "javascript"),
        ("/static/logo.svg", "image/svg+xml"),
        ("/static/favicon.svg", "image/svg+xml"),
        ("/static/favicon.ico", "icon"),
    ):
        r = anon.get(path)
        assert r.status_code == 200 and ctype in r.headers["content-type"], path


def test_all_pages_ok_after_login(web):
    vid = create_vehicle(web)
    create_sets(web, vid)
    web.post("/garages/new", {"name": "Garage Test", "email": "garage@example.invalid"})
    for url in [*STATIC_PAGES, *vehicle_pages(vid)]:
        r = web.get(url)
        assert r.status_code == 200, url
        assert "Wisselweer" in r.text


def test_empty_dashboard_has_add_button(web):
    r = web.get("/")
    assert "Voertuig toevoegen" in r.text and 'href="/vehicles/new"' in r.text


def test_login_page_is_styled_and_static(anon):
    r = anon.get("/login")
    assert "/static/app.css" in r.text and "/static/favicon.svg" in r.text


def test_vehicle_flow_set_change_history(web):
    vid = create_vehicle(web)
    page = web.get(f"/vehicles/{vid}")
    assert "Testauto" in page.text and "XX-000-X" in page.text

    create_sets(web, vid)
    detail = web.get(f"/vehicles/{vid}").text
    assert "ZomerMerk" in detail and "WinterMerk" in detail
    factory = ensure_db(web.c.app)
    with factory() as s:
        winter = s.scalar(select(TireSet).where(TireSet.brand == "WinterMerk"))

    r = web.post(
        f"/vehicles/{vid}/changes/new",
        {
            "changed_at": "2020-01-15",
            "to_set_id": str(winter.id),
            "odometer_km": "12345",
            "performed_by": "self",
            "cost": "49,50",
            "notes": "Zelf gedaan",
        },
    )
    assert r.status_code == 303, r.text[:1500]
    hist = web.c.get(r.headers["location"]).text
    assert "Wisselhistorie" in hist
    assert "Zelf gedaan" in hist and "12.345 km" in hist and "49,50" in hist
    with factory() as s:
        assert s.scalar(select(TireChange).where(TireChange.to_set_id == winter.id)) is not None
        assert s.get(TireSet, winter.id).status.value == "mounted"


def test_change_validation_error_is_shown(web):
    vid = create_vehicle(web)
    create_sets(web, vid)
    r = web.post(
        f"/vehicles/{vid}/changes/new", {"changed_at": "2999-01-01", "performed_by": "self"}
    )
    assert r.status_code == 422
    assert 'class="error"' in r.text


def test_tread_depth_and_km(web):
    vid = create_vehicle(web)
    r = web.post(
        f"/vehicles/{vid}/sets/new",
        {
            "type": "summer",
            "status": "mounted",
            "tread_FL": "6,5",
            "tread_RR": "5.0",
            "measured_at": "2024-03-01",
        },
    )
    assert r.status_code == 303
    page = web.get(f"/vehicles/{vid}").text
    assert "6,5 mm" in page and "5,0 mm" in page
    bad = web.post(f"/vehicles/{vid}/sets/new", {"type": "winter", "tread_FL": "99"})
    assert bad.status_code == 422


def test_vehicle_validation_errors(web):
    r = web.post("/vehicles/new", {**VEHICLE_FORM, "name": "", "latitude": "abc"})
    assert r.status_code == 422
    assert "Dit veld is verplicht." in r.text and "geldig getal" in r.text
    assert "Utrecht" in r.text  # ingevulde waarden blijven staan


def test_edit_location_profile_method_delete(web):
    vid = create_vehicle(web)
    web.post("/garages/new", {"name": "G1", "email": "garage@example.invalid"})
    r = web.post(f"/vehicles/{vid}/edit", {"name": "Nieuwe naam", "license_plate": "yy-111-y"})
    assert r.status_code == 303
    r = web.post(
        f"/vehicles/{vid}/location",
        {
            "location_name": "Groningen",
            "latitude": "53.2194",
            "longitude": "6.5665",
            "timezone": "Europe/Amsterdam",
        },
    )
    assert r.status_code == 303
    r = web.post(
        f"/vehicles/{vid}/method",
        {"change_method": "garage", "preferred_garage_id": "1", "prep_days": "10"},
    )
    assert r.status_code == 303
    r = web.post(
        f"/vehicles/{vid}/profile",
        {
            "preset": "custom",
            "slot_weekday": ["0", "0", "2"],
            "slot_start": ["07:00", "", "09:00"],
            "slot_end": ["08:30", "", "10:00"],
        },
    )
    assert r.status_code == 303, r.text[:1000]
    with ensure_db(web.c.app)() as s:
        v = s.get(Vehicle, vid)
        assert v.name == "Nieuwe naam" and v.license_plate == "YY111Y"
        assert v.prep_days == 10 and v.preferred_garage_id == 1
        assert v.driving_profile["kind"] == "custom" and len(v.driving_profile["slots"]) == 2
    page = web.get(f"/vehicles/{vid}").text
    assert "Groningen" in page and "Eigen weekschema" in page
    bad = web.post(
        f"/vehicles/{vid}/profile",
        {"preset": "custom", "slot_weekday": ["0"], "slot_start": ["10:00"], "slot_end": ["09:00"]},
    )
    assert bad.status_code == 422 and "Ongeldig tijdblok" in bad.text
    web.post(f"/vehicles/{vid}/profile", {"preset": "weekend"})
    with ensure_db(web.c.app)() as s:
        assert s.get(Vehicle, vid).driving_profile["kind"] == "weekend"

    assert "Ja, definitief verwijderen" in web.get(f"/vehicles/{vid}/delete").text
    r = web.post(f"/vehicles/{vid}/delete")
    assert r.status_code == 303
    assert web.get(f"/vehicles/{vid}").status_code == 404
    assert "Deze pagina bestaat niet" in web.get(f"/vehicles/{vid}").text


def test_odometer_add_and_correct(web):
    vid = create_vehicle(web)
    r = web.post(f"/vehicles/{vid}/odometer", {"reading_km": "1000", "recorded_on": "2024-01-01"})
    assert r.status_code == 303
    with ensure_db(web.c.app)() as s:
        reading = s.scalar(select(OdometerReading))
        rid = reading.id
    assert "1.000 km" in web.get(f"/vehicles/{vid}").text
    web.post(f"/vehicles/{vid}/odometer/{rid}/correct", {"reading_km": "1100", "note": "typfout"})
    page = web.get(f"/vehicles/{vid}").text
    assert "1.100 km" in page and "1.000 km" not in page
    with ensure_db(web.c.app)() as s:
        old = s.get(OdometerReading, rid)
        assert old.superseded_by_id is not None  # niet verwijderd


def test_garage_crud_and_appointment_mailto(web):
    r = web.post(
        "/garages/new",
        {
            "name": "Garage Test",
            "email": "garage@example.invalid",
            "lead_time_days": "10",
            "website": "javascript:alert(1)",
        },
    )
    assert r.status_code == 422  # alleen http(s)
    r = web.post(
        "/garages/new",
        {
            "name": "Garage Test",
            "email": "garage@example.invalid",
            "lead_time_days": "10",
            "website": "https://example.invalid",
        },
    )
    assert r.status_code == 303
    assert "Garage Test" in web.get("/garages").text

    vid = create_vehicle(web)
    web.post(
        f"/vehicles/{vid}/method",
        {"change_method": "garage", "preferred_garage_id": "1", "prep_days": "7"},
    )
    page = web.get(f"/vehicles/{vid}").text
    assert 'href="mailto:garage@example.invalid?subject=' in page
    assert "Afspraak aanvragen" in page

    r = web.post(
        f"/vehicles/{vid}/appointments",
        {
            "garage_id": "1",
            "direction": "to_winter",
            "period_start": "2024-11-01",
            "period_end": "2024-11-10",
            "notes": "z.s.m.",
        },
    )
    assert r.status_code == 303
    page = web.get(f"/vehicles/{vid}").text
    assert "Niet gepland" in page and "z.s.m." in page
    r = web.post(f"/vehicles/{vid}/appointments/1/status", {"status": "to_request"})
    assert r.status_code == 303
    assert "Nog aanvragen" in web.get(f"/vehicles/{vid}").text
    # ongeldige overgang geeft een nette melding, geen crash
    web.post(f"/vehicles/{vid}/appointments/1/status", {"status": "done"})
    assert web.get(f"/vehicles/{vid}").status_code == 200
    assert "Nog aanvragen" in web.get(f"/vehicles/{vid}").text

    r = web.post("/garages/1/edit", {"name": "Garage Nieuw", "lead_time_days": "5"})
    assert r.status_code == 303 and "Garage Nieuw" in web.get("/garages").text
    # garage met afspraken kan niet verwijderd worden: foutmelding via flash
    r = web.post("/garages/1/delete")
    assert r.status_code == 303
    assert "kan niet verwijderd" in web.c.get("/garages").text


def test_garage_delete(web):
    web.post("/garages/new", {"name": "Weg", "lead_time_days": "3"})
    r = web.post("/garages/1/delete")
    assert r.status_code == 303
    assert "Nog geen garages." in web.c.get("/garages").text


def test_csrf_required_on_all_posts(web):
    vid = create_vehicle(web)
    for url in (
        "/vehicles/new",
        f"/vehicles/{vid}/delete",
        "/garages/new",
        "/settings/provider",
        "/settings/tokens",
        f"/vehicles/{vid}/odometer",
    ):
        r = web.c.post(url, data={"name": "x"}, follow_redirects=False)
        assert r.status_code == 403, url
        r = web.c.post(url, data={"csrf_token": "fout"}, follow_redirects=False)
        assert r.status_code == 403, url
    with ensure_db(web.c.app)() as s:
        assert s.get(Vehicle, vid) is not None


def test_html_escapes_user_input(web):
    evil = "<script>alert(1)</script>"
    vid = create_vehicle(web, name=evil)
    web.post("/garages/new", {"name": evil, "lead_time_days": "1"})
    for url in ("/", f"/vehicles/{vid}", f"/vehicles/{vid}/edit", "/garages", "/settings"):
        text = web.get(url).text
        assert evil not in text, url
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in web.get("/").text
    r = web.post("/vehicles/new", {**VEHICLE_FORM, "name": "", "notes": '"><img src=x onerror=1>'})
    assert "<img src=x" not in r.text and "&lt;img src=x onerror=1&gt;" in r.text


INLINE = [
    re.compile(r"<style", re.I),
    re.compile(r"\sstyle\s*=", re.I),
    re.compile(r"<script(?![^>]*\ssrc=)", re.I),
    re.compile(r"<script[^>]*\ssrc=[^>]*>\s*[^<\s]", re.I),
    re.compile(r"\son[a-z]+\s*=", re.I),
    re.compile(r"javascript:", re.I),
]


def test_no_inline_scripts_or_styles(web, anon):
    vid = create_vehicle(web)
    create_sets(web, vid)
    web.post("/garages/new", {"name": "G", "email": "garage@example.invalid"})
    urls = [*STATIC_PAGES, *vehicle_pages(vid)]
    bodies = [web.get(u).text for u in urls] + [anon.get("/login").text]
    bodies.append(web.post("/settings/tokens", {"token_name": "ha"}).text)
    for body in bodies:
        for rx in INLINE:
            assert not rx.search(body), (rx.pattern, body[:200])
    for path in ("/static/app.css", "/static/app.js"):
        assert "http://" not in anon.get(path).text.replace("http://www.w3.org", "")
        assert "https://" not in anon.get(path).text
        assert "@import" not in anon.get(path).text


def test_security_headers_on_pages(web):
    r = web.get("/")
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_dashboard_shows_advice_and_weather(web):
    vid = create_vehicle(web)
    create_sets(web, vid)
    text = web.get("/").text
    assert "Wanneer winterbanden?" in text
    assert "Fake" in text  # bron van de laatste weerupdate
    assert "Laatste weerupdate" in text
    detail = web.get(f"/vehicles/{vid}").text
    assert (
        "Waarom dit advies?" in detail and "Hoe ver vooruit" in detail and "Onzekerheden" in detail
    )
    assert "Plan een afspraak vóór" in detail or "Nog geen betrouwbare wisseldatum" in detail


def test_dashboard_works_when_provider_fails(app, web):
    broken = FailingProvider()
    svc = ForecastService({"broken": broken}, ForecastCache(InMemoryBackend()), "broken")
    from wisselweer.api.deps import get_forecast_service

    app.dependency_overrides[get_forecast_service] = lambda: svc
    vid = create_vehicle(web)
    create_sets(web, vid)
    r = web.get("/")
    assert r.status_code == 200
    assert "Nog geen betrouwbare wisseldatum beschikbaar." in r.text
    assert "Geen weersverwachting beschikbaar" in r.text
    assert broken.calls >= 1
    assert web.get(f"/vehicles/{vid}").status_code == 200


def test_dashboard_survives_unexpected_advice_error(app, web, monkeypatch):
    from wisselweer.vehicles.advice import VehicleAdviceService

    vid = create_vehicle(web)

    def boom(self, vehicle_id, now):
        raise RuntimeError("kapot")

    monkeypatch.setattr(VehicleAdviceService, "advice_for_vehicle", boom)
    r = web.get("/")
    assert r.status_code == 200 and "kon nu niet worden berekend" in r.text
    assert web.get(f"/vehicles/{vid}").status_code == 200


def test_provider_choice_saved_and_used(app, web, provider, other_provider):
    vid = create_vehicle(web)
    create_sets(web, vid)
    web.get("/")
    assert provider.calls >= 1 and other_provider.calls == 0

    page = web.get("/settings").text
    assert "Weerbronnen" in page and "Fake data" in page and "Andere bron" in page

    r = web.post("/settings/provider", {"provider": "nope"})
    assert r.status_code == 303
    assert "niet beschikbaar" in web.c.get("/settings").text

    r = web.post("/settings/provider", {"provider": "other"})
    assert r.status_code == 303
    with ensure_db(app)() as s:
        assert s.get(AppSetting, "default_provider").value == "other"
    assert app.state.test_service.default_provider == "other"
    before = other_provider.calls
    web.get(f"/vehicles/{vid}")
    assert other_provider.calls > before


def test_saved_provider_overrides_env_default(app):
    svc = ForecastService(
        {"a": object(), "b": object()},
        ForecastCache(InMemoryBackend()),
        "a",  # type: ignore[dict-item]
    )
    factory = ensure_db(app)
    apply_default_provider_setting(factory, svc)
    assert svc.default_provider == "a"
    with factory() as s:
        s.add(AppSetting(key="default_provider", value="b"))
        s.commit()
    apply_default_provider_setting(factory, svc)
    assert svc.default_provider == "b"
    with factory() as s:
        s.merge(AppSetting(key="default_provider", value="onbekend"))
        s.commit()
    svc2 = ForecastService({"a": object()}, ForecastCache(InMemoryBackend()), "a")  # type: ignore[dict-item]
    apply_default_provider_setting(factory, svc2)
    assert svc2.default_provider == "a"


def test_settings_compare_and_tokens(web):
    vid = create_vehicle(web)
    page = web.get("/settings?location=1").text
    assert "Alleen ter vergelijking, niet gecombineerd" in page
    assert "<table" in page and "Fake" in page and "Andere bron" in page
    assert 'href="/docs"' in page
    assert "Utrecht" in page
    del vid

    r = web.post("/settings/tokens", {"token_name": "homeassistant"})
    assert r.status_code == 200
    token = re.search(r"wwt_[A-Za-z0-9_-]+", r.text).group(0)
    assert r.headers["cache-control"] == "no-store"
    again = web.get("/settings").text
    assert "homeassistant" in again and token not in again
    # het token werkt op de API
    api = web.c.get("/api/v1/providers", headers={"Authorization": f"Bearer {token}"})
    assert api.status_code == 200
    dup = web.post("/settings/tokens", {"token_name": "homeassistant"})
    assert dup.status_code == 303
    assert "bestaat al" in web.c.get("/settings").text

    r = web.post("/settings/tokens/revoke", {"token_name": "homeassistant"})
    assert r.status_code == 303
    tokens_section = web.c.get("/settings").text.split('id="sec-tokens"')[1].split("</section>")[0]
    assert "homeassistant" not in tokens_section.split("<form")[0]
    api = web.c.get("/api/v1/providers", headers={"Authorization": f"Bearer {token}"})
    assert api.status_code == 401


def test_logout_button(web):
    assert 'action="/logout"' in web.get("/").text
    r = web.post("/logout")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert web.get("/").status_code == 303


def test_language_switch_and_date_format(web):
    r = web.get("/?lang=en")
    assert "Overview" in r.text and 'lang="en"' in r.text
    assert "Overzicht" in web.get("/?lang=nl-NL").text
    assert "Overzicht" in web.get("/?lang=xx").text  # onbekende taal: standaard
