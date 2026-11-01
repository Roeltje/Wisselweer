"""Server-rendered beheerinterface (POST -> redirect -> GET); alle pagina's achter login."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from wisselweer.api import auth
from wisselweer.api.auth import require_user_html
from wisselweer.api.deps import (
    DEFAULT_PROVIDER_KEY,
    get_advice_service,
    get_forecast_service,
    get_session_factory,
)
from wisselweer.core.models import (
    Direction,
    DriveSlot,
    DrivingProfile,
    ProfileKind,
    TireType,
)
from wisselweer.garages import service as garage_svc
from wisselweer.garages.schemas import AppointmentIn, GarageIn, GaragePatch
from wisselweer.i18n import SUPPORTED_LOCALES, format_date, normalize_locale
from wisselweer.storage.db import session_scope
from wisselweer.storage.enums import (
    AppointmentStatus,
    ChangeMethod,
    Position,
    TireStatus,
)
from wisselweer.storage.errors import InvalidOperation, NotFoundError
from wisselweer.storage.orm import ApiToken, AppSetting, Location, Vehicle
from wisselweer.tires import service as tire_svc
from wisselweer.tires.schemas import (
    TireGroupIn,
    TireGroupPatch,
    TireReplaceIn,
    TireSetIn,
    TireSetPatch,
    TreadMeasurementIn,
)
from wisselweer.vehicles import service as vehicle_svc
from wisselweer.vehicles.schemas import LocationIn, VehicleIn, VehicleOut, VehiclePatch
from wisselweer.weather.base import ProviderError
from wisselweer.weather.compare import compare_forecasts
from wisselweer.web import tire_forms, views
from wisselweer.web.forms import (
    Field,
    Form,
    Parser,
    bind,
    parse_local_datetime,
    parse_time,
    read_form,
)
from wisselweer.web.templating import templates

log = logging.getLogger("wisselweer.web")

STATIC_DIR = Path(__file__).parent / "static"
static_files = StaticFiles(directory=str(STATIC_DIR))

router = APIRouter(dependencies=[Depends(require_user_html)], include_in_schema=False)

Factory = Annotated[sessionmaker[Session], Depends(get_session_factory)]
FormDep = Annotated[Form, Depends(read_form)]
Forecasts = Annotated[Any, Depends(get_forecast_service)]
Advisor = Annotated[Any, Depends(get_advice_service)]

DEFAULT_TZ = "Europe/Amsterdam"


# --------------------------------------------------------------------------- hulpfuncties


def current_locale(request: Request) -> str:
    lang = request.query_params.get("lang")
    if lang in SUPPORTED_LOCALES:
        request.session["lang"] = lang
    return normalize_locale(request.session.get("lang"))


def flash(request: Request, text: str, kind: str = "ok") -> None:
    items = request.session.get("flash")
    items = items if isinstance(items, list) else []
    items.append([kind, text[:300]])
    request.session["flash"] = items[-3:]


def render(
    request: Request,
    name: str,
    ctx: dict[str, Any] | None = None,
    *,
    status: int = 200,
    nav: str = "",
) -> Response:
    locale = current_locale(request)
    flashes = request.session.pop("flash", []) if "flash" in request.session else []
    context: dict[str, Any] = {
        "locale": locale,
        "locales": SUPPORTED_LOCALES,
        "nav": nav,
        "authed": True,
        "flashes": flashes,
        "tr": views.make_tr(locale),
    }
    context.update(ctx or {})
    response = templates.TemplateResponse(request, name, context, status_code=status)
    response.headers["Cache-Control"] = "no-store"
    return response


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def not_found_page(request: Request) -> Response:
    return render(request, "error.html", {"code": 404}, status=404)


def opts(enum: Any, prefix: str, tr: Any, only: list[Any] | None = None) -> tuple:
    return tuple((m.value, tr(f"{prefix}.{m.value}")) for m in (only or list(enum)))


def form_page(
    request: Request,
    *,
    title: str,
    fields: list[Field],
    action: str,
    cancel: str,
    submit: str = "action.save",
    errors: list[str] | None = None,
    intro: str | None = None,
    nav: str = "vehicles",
    status: int = 200,
    ctx: dict[str, Any] | None = None,
) -> Response:
    # Locatieformulieren krijgen de zoekhulp; "enabled" = geocoderen staat aan (anders alleen
    # de knop "Gebruik mijn locatie", die geen externe dienst gebruikt).
    is_location = any(f.name == "latitude" for f in fields)
    geo = {"enabled": request.app.state.settings.geocoding_enabled} if is_location else None
    return render(
        request,
        "form.html",
        {
            "geo": geo,
            "title": title,
            "fields": fields,
            "action": action,
            "cancel": cancel,
            "submit": submit,
            "form_errors": errors or [],
            "intro": intro,
            **(ctx or {}),
        },
        nav=nav,
        status=status,
    )


def local_today(tz_name: str) -> date:
    return datetime.now(views.tz_of(tz_name)).date()


def to_utc(local_naive: datetime, tz_name: str) -> datetime:
    return local_naive.replace(tzinfo=views.tz_of(tz_name)).astimezone(UTC)


def _warn_years(request: Request) -> float:
    return float(request.app.state.settings.tire_age_warn_years)


def service_error(exc: Exception) -> str:
    if isinstance(exc, IntegrityError):
        return "conflict"
    return str(exc)[:200]


# --------------------------------------------------------------------------- dashboard


def _compute_advice(advisor: Any, vehicle_id: int, now: datetime) -> Any | None:
    try:
        return advisor.advice_for_vehicle(vehicle_id, now)
    except NotFoundError:
        raise
    except Exception as exc:  # noqa: BLE001 - de pagina moet blijven werken
        log.warning("advice_failed type=%s", type(exc).__name__)
        return None


def _card(
    factory: sessionmaker[Session],
    advisor: Any,
    vehicle: VehicleOut,
    infos: list[Any],
    locale: str,
    now: datetime,
) -> tuple[views.VehicleCard, Any | None]:
    tz = views.tz_of(vehicle.timezone)
    advice = _compute_advice(advisor, vehicle.id, now)
    with session_scope(factory) as s:
        sets = tire_svc.list_tire_sets(s, vehicle.id)
        mounted = views.mounted_set(sets)
        weather = views.last_weather(s, vehicle.id, infos, locale, tz)
        appointment = views.next_appointment(s, vehicle.id, locale, tz, now)
    advice_view = (
        views.build_advice_view(advice, locale, tz, infos, no_mounted=mounted is None)
        if advice is not None
        else None
    )
    card = views.VehicleCard(
        vehicle=vehicle,
        mounted=mounted,
        advice=advice_view,
        advice_failed=advice is None,
        appointment=appointment,
        weather=weather,
    )
    return card, advice


@router.get("/")
def dashboard(
    request: Request, factory: Factory, forecasts: Forecasts, advisor: Advisor
) -> Response:
    locale = current_locale(request)
    infos = forecasts.provider_infos()
    now = datetime.now(UTC)
    with session_scope(factory) as s:
        vehicles = vehicle_svc.list_vehicles(s)
    cards = [_card(factory, advisor, v, infos, locale, now)[0] for v in vehicles]
    return render(request, "dashboard.html", {"cards": cards}, nav="dashboard")


# --------------------------------------------------------------------------- voertuigen


def vehicle_fields(tr: Any) -> list[Field]:
    return [
        Field("name", "vehicle.name", required=True, attrs={"maxlength": "120"}),
        Field("make", "vehicle.make", attrs={"maxlength": "80"}),
        Field("model", "vehicle.model", attrs={"maxlength": "80"}),
        Field("license_plate", "vehicle.license_plate", attrs={"maxlength": "20"}),
        Field(
            "build_year",
            "vehicle.build_year",
            attrs={"inputmode": "numeric", "maxlength": "4"},
        ),
        Field("notes", "vehicle.notes", kind="textarea"),
    ]


def location_fields(tr: Any) -> list[Field]:
    return [
        Field("location_name", "location.name", required=True, attrs={"maxlength": "120"}),
        Field(
            "latitude",
            "location.latitude",
            required=True,
            help="location.coords_help",
            attrs={"inputmode": "decimal", "placeholder": "52.0907"},
        ),
        Field(
            "longitude",
            "location.longitude",
            required=True,
            attrs={"inputmode": "decimal", "placeholder": "5.1214"},
        ),
        Field("timezone", "location.timezone", value=DEFAULT_TZ, required=True),
    ]


def _parse_location(p: Parser) -> LocationIn | None:
    name = p.text("location_name", required=True, max_len=120)
    lat = p.decimal("latitude", required=True, minimum=-90, maximum=90)
    lon = p.decimal("longitude", required=True, minimum=-180, maximum=180)
    tz = p.text("timezone", required=True, max_len=64) or DEFAULT_TZ
    if p.errors or name is None or lat is None or lon is None:
        return None
    try:
        return LocationIn(name=name, latitude=lat, longitude=lon, timezone=tz)
    except ValidationError as exc:
        p.apply_validation_error(exc, ["timezone", "name"])
        return None


def _parse_vehicle_basics(p: Parser) -> dict[str, Any]:
    return {
        "name": p.text("name", required=True, max_len=120),
        "make": p.text("make", max_len=80),
        "model": p.text("model", max_len=80),
        "license_plate": p.text("license_plate", max_len=20),
        "build_year": p.integer("build_year", minimum=1900, maximum=2100),
        "notes": p.text("notes", max_len=2000),
    }


def get_vehicle_or_404(s: Session, vehicle_id: int) -> VehicleOut:
    return vehicle_svc.get_vehicle(s, vehicle_id)


@router.get("/vehicles/new")
def vehicle_new(request: Request) -> Response:
    tr = views.make_tr(current_locale(request))
    fields = bind(vehicle_fields(tr) + location_fields(tr), {}, {})
    return form_page(
        request,
        title=tr("vehicle.new"),
        fields=fields,
        action="/vehicles/new",
        cancel="/",
        submit="vehicle.create",
    )


@router.post("/vehicles/new")
def vehicle_create(request: Request, form: FormDep, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    basics = _parse_vehicle_basics(p)
    loc = _parse_location(p)
    rest: list[str] = []
    if not p.errors and loc is not None:
        try:
            data = VehicleIn(
                location=loc,
                timezone=loc.timezone,
                driving_profile=DrivingProfile.commute(),
                **basics,
            )
            with session_scope(factory) as s:
                v = vehicle_svc.create_vehicle(s, data)
            flash(request, tr("flash.vehicle_created"))
            return redirect(f"/vehicles/{v.id}")
        except ValidationError as exc:
            rest = p.apply_validation_error(exc, list(basics))
        except (InvalidOperation, IntegrityError) as exc:
            rest = [service_error(exc)]
    fields = bind(vehicle_fields(tr) + location_fields(tr), form.values(), p.errors)
    return form_page(
        request,
        title=tr("vehicle.new"),
        fields=fields,
        action="/vehicles/new",
        cancel="/",
        submit="vehicle.create",
        errors=rest,
        status=422,
    )


@router.get("/vehicles/{vehicle_id}")
def vehicle_detail(
    request: Request,
    vehicle_id: int,
    factory: Factory,
    forecasts: Forecasts,
    advisor: Advisor,
) -> Response:
    locale = current_locale(request)
    tr = views.make_tr(locale)
    infos = forecasts.provider_infos()
    now = datetime.now(UTC)
    with session_scope(factory) as s:
        vehicle = get_vehicle_or_404(s, vehicle_id)
    card, advice = _card(factory, advisor, vehicle, infos, locale, now)
    tz = views.tz_of(vehicle.timezone)
    with session_scope(factory) as s:
        sets = tire_svc.list_tire_sets(s, vehicle_id)
        garages = garage_svc.list_garages(s)
        garage_by_id = {g.id: g for g in garages}
        set_rows = views.tire_set_rows(s, vehicle_id, locale, _warn_years(request))
        changes = views.change_rows(s, vehicle_id, sets, garage_by_id, locale)
        readings = [
            {
                "id": r.id,
                "km": r.reading_km,
                "at": format_date(r.recorded_at.astimezone(tz), locale),
                "source": tr(f"odometer.source.{r.source.value}"),
                "note": r.note,
            }
            for r in reversed(tire_svc.list_odometer_readings(s, vehicle_id))
        ]
        appts = [
            views.appointment_view(a, garage_by_id, locale, tz)
            for a in reversed(garage_svc.list_appointments(s, vehicle_id))
        ]
    preferred = garage_by_id.get(vehicle.preferred_garage_id or 0)

    def mail(g: Any) -> str | None:
        if g is None or not g.email:
            return None
        return garage_svc.mailto_link(vehicle, g, advice)

    for a in appts:
        a["mailto"] = mail(a["garage"])
    default_dir = (
        advice.direction
        if advice is not None and advice.direction != Direction.NONE
        else Direction.TO_WINTER
    )
    today = local_today(vehicle.timezone)
    appt_fields = bind(
        appointment_fields(tr, garages),
        {
            "direction": default_dir.value,
            "garage_id": str(vehicle.preferred_garage_id or ""),
            "period_start": (
                advice.recommended_period[0].isoformat()
                if advice and advice.recommended_period
                else (
                    advice.recommended_date.isoformat()
                    if advice and advice.recommended_date
                    else ""
                )
            ),
            "period_end": (
                advice.recommended_period[1].isoformat()
                if advice and advice.recommended_period
                else ""
            ),
        },
        {},
    )
    odo_fields = bind(odometer_fields(), {"recorded_on": today.isoformat()}, {})
    return render(
        request,
        "vehicle_detail.html",
        {
            "v": vehicle,
            "card": card,
            "profile_text": views.profile_summary(vehicle.driving_profile, locale),
            "method_text": tr(f"method.{vehicle.change_method.value}"),
            "preferred": preferred,
            "mailto": mail(preferred),
            "sets": set_rows,
            "changes": changes,
            "readings": readings,
            "appointments": appts,
            "appt_fields": appt_fields,
            "odo_fields": odo_fields,
            "has_garages": bool(garages),
            "can_change": any(r["set"].status == TireStatus.STORED for r in set_rows),
        },
        nav="vehicles",
    )


@router.get("/vehicles/{vehicle_id}/edit")
def vehicle_edit(request: Request, vehicle_id: int, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    with session_scope(factory) as s:
        v = get_vehicle_or_404(s, vehicle_id)
    values = {
        "name": v.name,
        "make": v.make or "",
        "model": v.model or "",
        "license_plate": v.license_plate or "",
        "build_year": str(v.build_year or ""),
        "notes": v.notes or "",
    }
    return form_page(
        request,
        title=tr("vehicle.edit"),
        fields=bind(vehicle_fields(tr), values, {}),
        action=f"/vehicles/{vehicle_id}/edit",
        cancel=f"/vehicles/{vehicle_id}",
    )


@router.post("/vehicles/{vehicle_id}/edit")
def vehicle_update(request: Request, vehicle_id: int, form: FormDep, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    basics = _parse_vehicle_basics(p)
    rest: list[str] = []
    if not p.errors:
        try:
            patch = VehiclePatch(**basics)
            with session_scope(factory) as s:
                vehicle_svc.update_vehicle(s, vehicle_id, patch)
            flash(request, tr("flash.saved"))
            return redirect(f"/vehicles/{vehicle_id}")
        except ValidationError as exc:
            rest = p.apply_validation_error(exc, list(basics))
        except (InvalidOperation, IntegrityError) as exc:
            rest = [service_error(exc)]
    return form_page(
        request,
        title=tr("vehicle.edit"),
        fields=bind(vehicle_fields(tr), form.values(), p.errors),
        action=f"/vehicles/{vehicle_id}/edit",
        cancel=f"/vehicles/{vehicle_id}",
        errors=rest,
        status=422,
    )


@router.get("/vehicles/{vehicle_id}/delete")
def vehicle_delete_confirm(request: Request, vehicle_id: int, factory: Factory) -> Response:
    with session_scope(factory) as s:
        v = get_vehicle_or_404(s, vehicle_id)
    return render(request, "confirm_delete.html", {"v": v}, nav="vehicles")


@router.post("/vehicles/{vehicle_id}/delete")
def vehicle_delete(request: Request, vehicle_id: int, form: FormDep, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    with session_scope(factory) as s:
        vehicle_svc.delete_vehicle(s, vehicle_id)
    flash(request, tr("flash.vehicle_deleted"))
    return redirect("/")


@router.get("/vehicles/{vehicle_id}/location")
def location_edit(request: Request, vehicle_id: int, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    with session_scope(factory) as s:
        v = get_vehicle_or_404(s, vehicle_id)
    values = {
        "location_name": v.location.name,
        "latitude": str(v.location.latitude),
        "longitude": str(v.location.longitude),
        "timezone": v.location.timezone,
    }
    return form_page(
        request,
        title=tr("location.edit"),
        fields=bind(location_fields(tr), values, {}),
        action=f"/vehicles/{vehicle_id}/location",
        cancel=f"/vehicles/{vehicle_id}",
    )


@router.post("/vehicles/{vehicle_id}/location")
def location_update(request: Request, vehicle_id: int, form: FormDep, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    loc = _parse_location(p)
    rest: list[str] = []
    if loc is not None and not p.errors:
        try:
            with session_scope(factory) as s:
                vehicle_svc.update_vehicle(
                    s, vehicle_id, VehiclePatch(location=loc, timezone=loc.timezone)
                )
            flash(request, tr("flash.saved"))
            return redirect(f"/vehicles/{vehicle_id}")
        except (InvalidOperation, IntegrityError) as exc:
            rest = [service_error(exc)]
    return form_page(
        request,
        title=tr("location.edit"),
        fields=bind(location_fields(tr), form.values(), p.errors),
        action=f"/vehicles/{vehicle_id}/location",
        cancel=f"/vehicles/{vehicle_id}",
        errors=rest,
        status=422,
    )


def method_fields(tr: Any, garages: list[Any]) -> list[Field]:
    return [
        Field(
            "change_method",
            "method.label",
            kind="select",
            required=True,
            options=opts(ChangeMethod, "method", tr),
        ),
        Field(
            "preferred_garage_id",
            "method.preferred_garage",
            kind="select",
            options=(("", tr("common.none")), *((str(g.id), g.name) for g in garages)),
        ),
        Field(
            "prep_days",
            "method.prep_days",
            required=True,
            help="method.prep_days_help",
            attrs={"inputmode": "numeric"},
        ),
    ]


@router.get("/vehicles/{vehicle_id}/method")
def method_edit(request: Request, vehicle_id: int, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    with session_scope(factory) as s:
        v = get_vehicle_or_404(s, vehicle_id)
        garages = garage_svc.list_garages(s)
    values = {
        "change_method": v.change_method.value,
        "preferred_garage_id": str(v.preferred_garage_id or ""),
        "prep_days": str(v.prep_days),
    }
    return form_page(
        request,
        title=tr("method.edit"),
        fields=bind(method_fields(tr, garages), values, {}),
        action=f"/vehicles/{vehicle_id}/method",
        cancel=f"/vehicles/{vehicle_id}",
    )


@router.post("/vehicles/{vehicle_id}/method")
def method_update(request: Request, vehicle_id: int, form: FormDep, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    method = p.choice("change_method", ChangeMethod)
    garage_id = p.optional_id("preferred_garage_id")
    prep = p.integer("prep_days", required=True, minimum=0, maximum=365)
    rest: list[str] = []
    if not p.errors and method is not None and prep is not None:
        try:
            with session_scope(factory) as s:
                vehicle_svc.update_vehicle(
                    s,
                    vehicle_id,
                    VehiclePatch(
                        change_method=method, preferred_garage_id=garage_id, prep_days=prep
                    ),
                )
            flash(request, tr("flash.saved"))
            return redirect(f"/vehicles/{vehicle_id}")
        except (InvalidOperation, NotFoundError) as exc:
            if isinstance(exc, NotFoundError) and "garage" not in str(exc):
                raise
            rest = [service_error(exc)]
    with session_scope(factory) as s:
        garages = garage_svc.list_garages(s)
    return form_page(
        request,
        title=tr("method.edit"),
        fields=bind(method_fields(tr, garages), form.values(), p.errors),
        action=f"/vehicles/{vehicle_id}/method",
        cancel=f"/vehicles/{vehicle_id}",
        errors=rest,
        status=422,
    )


# --- rijprofiel


def _slot_days(slots: list[tuple[int, str, str]], tr: Any) -> list[dict]:
    """Per weekdag de tijdblokken plus één leeg blok om aan toe te voegen."""
    days = []
    for wd in range(7):
        rows = [{"start": a, "end": b} for w, a, b in slots if w == wd]
        rows.append({"start": "", "end": ""})
        days.append({"weekday": wd, "name": tr(f"weekday.{wd}"), "rows": rows})
    return days


def _profile_page(
    request: Request,
    vehicle: VehicleOut,
    kind: str,
    slots: list[tuple[int, str, str]],
    errors: list[str],
    status: int = 200,
) -> Response:
    tr = views.make_tr(current_locale(request))
    return render(
        request,
        "profile_form.html",
        {
            "v": vehicle,
            "kind": kind,
            "kinds": [(k.value, tr(f"profile.{k.value}")) for k in ProfileKind],
            "days": _slot_days(slots, tr),
            "form_errors": errors,
        },
        nav="vehicles",
        status=status,
    )


@router.get("/vehicles/{vehicle_id}/profile")
def profile_edit(request: Request, vehicle_id: int, factory: Factory) -> Response:
    with session_scope(factory) as s:
        v = get_vehicle_or_404(s, vehicle_id)
    slots = [(sl.weekday, f"{sl.start:%H:%M}", f"{sl.end:%H:%M}") for sl in v.driving_profile.slots]
    return _profile_page(request, v, v.driving_profile.kind.value, slots, [])


@router.post("/vehicles/{vehicle_id}/profile")
def profile_update(request: Request, vehicle_id: int, form: FormDep, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    kind_raw = form.get("preset")
    try:
        kind = ProfileKind(kind_raw)
    except ValueError:
        kind = ProfileKind.COMMUTE
    raw = list(
        zip(
            form.getlist("slot_weekday"),
            form.getlist("slot_start"),
            form.getlist("slot_end"),
            strict=False,
        )
    )
    errors: list[str] = []
    profile: DrivingProfile | None = None
    parsed: list[tuple[int, str, str]] = [(int(w) if w.isdigit() else 0, a, b) for w, a, b in raw]
    if kind == ProfileKind.CUSTOM:
        slots: list[DriveSlot] = []
        for w, a, b in raw:
            if not a and not b:
                continue
            ta, tb = parse_time(a), parse_time(b)
            if not w.isdigit() or int(w) > 6 or ta is None or tb is None or tb <= ta:
                errors.append(
                    tr(
                        "error.slot",
                        day=tr(f"weekday.{int(w) if w.isdigit() and int(w) < 7 else 0}"),
                    )
                )
                continue
            slots.append(DriveSlot(weekday=int(w), start=ta, end=tb))
        if not slots and not errors:
            errors.append(tr("error.slots_required"))
        if not errors:
            profile = DrivingProfile.custom(slots)
    else:
        profile = {
            ProfileKind.COMMUTE: DrivingProfile.commute,
            ProfileKind.DAYTIME: DrivingProfile.daytime,
            ProfileKind.WEEKEND: DrivingProfile.weekend,
        }[kind]()
    if profile is not None:
        with session_scope(factory) as s:
            vehicle_svc.update_vehicle(s, vehicle_id, VehiclePatch(driving_profile=profile))
        flash(request, tr("flash.saved"))
        return redirect(f"/vehicles/{vehicle_id}")
    with session_scope(factory) as s:
        v = get_vehicle_or_404(s, vehicle_id)
    return _profile_page(request, v, kind.value, parsed, errors, status=422)


# --------------------------------------------------------------------------- bandensets


def set_fields(tr: Any, *, status_options: tuple, with_groups: bool = False) -> list[Field]:
    positions = [
        Field(
            f"tread_{pos.value}",
            f"tread.{pos.value}",
            attrs={"inputmode": "decimal", "placeholder": "mm"},
        )
        for pos in Position
        if pos != Position.ALL
    ]
    return [
        Field(
            "type",
            "tire.type",
            kind="select",
            required=True,
            options=opts(TireType, "tire.type", tr),
        ),
        Field("brand", "tire.brand", attrs={"maxlength": "80"}),
        Field("model", "tire.model", attrs={"maxlength": "80"}),
        Field(
            "size",
            "tire.size",
            help="tire.size_help",
            attrs={"maxlength": "40", "placeholder": "205/55 R16 91H"},
        ),
        *([Field("tire_groups", "tire.groups", kind="groups")] if with_groups else []),
        Field("price", "tire.price", attrs={"inputmode": "decimal"}),
        Field("status", "tire.status", kind="select", required=True, options=status_options),
        Field("notes", "tire.notes", kind="textarea"),
        Field("measured_at", "tread.measured_at", kind="date", help="tread.help"),
        *positions,
    ]


def _status_options(tr: Any, current: TireStatus | None) -> tuple:
    allowed = [TireStatus.STORED, TireStatus.RETIRED]
    if current in (None, TireStatus.MOUNTED):
        allowed.insert(0, TireStatus.MOUNTED)
    return opts(TireStatus, "tire.status", tr, allowed)


def _parse_set(p: Parser) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": p.choice("type", TireType),
        "brand": p.text("brand", max_len=80),
        "model": p.text("model", max_len=80),
        "size": p.text("size", max_len=40),
        "purchase_price_cents": p.cents("price"),
        "notes": p.text("notes", max_len=2000),
        "status": p.choice("status", TireStatus),
    }
    return out


def _parse_tread(p: Parser) -> list[TreadMeasurementIn]:
    measured = p.date("measured_at")
    out = []
    for pos in Position:
        if pos == Position.ALL:
            continue
        depth = p.decimal(f"tread_{pos.value}", minimum=0, maximum=20)
        if depth is not None:
            out.append(
                TreadMeasurementIn(
                    measured_at=measured or date.today(), position=pos, depth_mm=depth
                )
            )
    return out


def _vehicle_set(s: Session, vehicle_id: int, set_id: int) -> Any:
    ts = tire_svc.get_tire_set(s, set_id)
    if ts.vehicle_id != vehicle_id:
        raise NotFoundError("bandenset niet gevonden")
    return ts


@router.get("/vehicles/{vehicle_id}/sets/new")
def set_new(request: Request, vehicle_id: int, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    with session_scope(factory) as s:
        v = get_vehicle_or_404(s, vehicle_id)
        has_mounted = views.mounted_set(tire_svc.list_tire_sets(s, vehicle_id)) is not None
    options = _status_options(tr, TireStatus.STORED if has_mounted else None)
    values = {
        "status": "stored" if has_mounted else "mounted",
        "measured_at": local_today(v.timezone).isoformat(),
    }
    return form_page(
        request,
        title=tr("tire.new"),
        fields=bind(set_fields(tr, status_options=options, with_groups=True), values, {}),
        action=f"/vehicles/{vehicle_id}/sets/new",
        cancel=f"/vehicles/{vehicle_id}",
        submit="tire.create",
        ctx={"groups": tire_forms.group_rows(values, {})},
    )


@router.post("/vehicles/{vehicle_id}/sets/new")
def set_create(request: Request, vehicle_id: int, form: FormDep, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    raw = _parse_set(p)
    treads = _parse_tread(p)
    groups = tire_forms.parse_new_groups(p, form, raw["type"])
    rest: list[str] = []
    if not p.errors:
        try:
            data = TireSetIn(**raw, tire_groups=groups)
            with session_scope(factory) as s:
                created = tire_svc.create_tire_set(s, vehicle_id, data)
                for m in treads:
                    tire_svc.add_tread_measurement(s, created.id, m)
            flash(request, tr("flash.set_created"))
            return redirect(f"/vehicles/{vehicle_id}#sets")
        except ValidationError as exc:
            rest = p.apply_validation_error(exc, list(raw))
        except InvalidOperation as exc:
            rest = [service_error(exc)]
    options = _status_options(tr, None)
    return form_page(
        request,
        title=tr("tire.new"),
        fields=bind(
            set_fields(tr, status_options=options, with_groups=True), form.values(), p.errors
        ),
        action=f"/vehicles/{vehicle_id}/sets/new",
        cancel=f"/vehicles/{vehicle_id}",
        submit="tire.create",
        errors=rest,
        status=422,
        ctx={"groups": tire_forms.group_rows(form.values(), p.errors)},
    )


@router.get("/vehicles/{vehicle_id}/sets/{set_id}/edit")
def set_edit(request: Request, vehicle_id: int, set_id: int, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    with session_scope(factory) as s:
        v = get_vehicle_or_404(s, vehicle_id)
        ts = _vehicle_set(s, vehicle_id, set_id)
    price = (
        ""
        if ts.purchase_price_cents is None
        else f"{ts.purchase_price_cents / 100:.2f}".replace(".", ",")
    )
    values = {
        "type": ts.type.value,
        "brand": ts.brand or "",
        "model": ts.model or "",
        "size": ts.size or "",
        "price": price,
        "status": ts.status.value,
        "notes": ts.notes or "",
        "measured_at": local_today(v.timezone).isoformat(),
    }
    return form_page(
        request,
        title=tr("tire.edit"),
        fields=bind(set_fields(tr, status_options=_status_options(tr, ts.status)), values, {}),
        action=f"/vehicles/{vehicle_id}/sets/{set_id}/edit",
        cancel=f"/vehicles/{vehicle_id}",
    )


@router.post("/vehicles/{vehicle_id}/sets/{set_id}/edit")
def set_update(
    request: Request, vehicle_id: int, set_id: int, form: FormDep, factory: Factory
) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    raw = _parse_set(p)
    treads = _parse_tread(p)
    rest: list[str] = []
    with session_scope(factory) as s:
        current = _vehicle_set(s, vehicle_id, set_id)
    if not p.errors:
        try:
            patch = TireSetPatch(**raw)
            with session_scope(factory) as s:
                tire_svc.update_tire_set(s, set_id, patch)
                for m in treads:
                    tire_svc.add_tread_measurement(s, set_id, m)
            flash(request, tr("flash.saved"))
            return redirect(f"/vehicles/{vehicle_id}#sets")
        except ValidationError as exc:
            rest = p.apply_validation_error(exc, list(raw))
        except InvalidOperation as exc:
            rest = [service_error(exc)]
    return form_page(
        request,
        title=tr("tire.edit"),
        fields=bind(
            set_fields(tr, status_options=_status_options(tr, current.status)),
            form.values(),
            p.errors,
        ),
        action=f"/vehicles/{vehicle_id}/sets/{set_id}/edit",
        cancel=f"/vehicles/{vehicle_id}",
        errors=rest,
        status=422,
    )


@router.post("/vehicles/{vehicle_id}/sets/{set_id}/delete")
def set_delete(
    request: Request, vehicle_id: int, set_id: int, form: FormDep, factory: Factory
) -> Response:
    tr = views.make_tr(current_locale(request))
    try:
        with session_scope(factory) as s:
            _vehicle_set(s, vehicle_id, set_id)
            tire_svc.delete_tire_set(s, set_id)
        flash(request, tr("flash.set_deleted"))
    except InvalidOperation as exc:
        flash(request, service_error(exc), "error")
    return redirect(f"/vehicles/{vehicle_id}#sets")


# --- setpagina en bandengroepen


@router.get("/vehicles/{vehicle_id}/sets/{set_id}")
def set_detail(request: Request, vehicle_id: int, set_id: int, factory: Factory) -> Response:
    locale = current_locale(request)
    with session_scope(factory) as s:
        v = get_vehicle_or_404(s, vehicle_id)
        detail = views.set_detail(s, vehicle_id, set_id, locale, _warn_years(request))
    return render(
        request,
        "set_detail.html",
        {"v": v, "d": detail, "warn_years": f"{_warn_years(request):g}"},
        nav="vehicles",
    )


def _group_page(
    request: Request,
    factory: Factory,
    vehicle_id: int,
    set_id: int,
    *,
    mode: str,
    group_id: int | None = None,
    values: dict[str, str] | None = None,
    errors: dict[str, str] | None = None,
    rest: list[str] | None = None,
    status: int = 200,
) -> Response:
    """Formulier om groepen toe te voegen, te wijzigen of te vervangen."""
    tr = views.make_tr(current_locale(request))
    with session_scope(factory) as s:
        v = get_vehicle_or_404(s, vehicle_id)
        ts = tire_svc.get_tire_set(s, set_id)
        if ts.vehicle_id != vehicle_id:
            raise NotFoundError("bandenset niet gevonden")
        group = tire_svc.get_tire_group(s, group_id) if group_id is not None else None
        if group is not None and (group.tire_set_id != set_id or group.removed_on is not None):
            raise NotFoundError("bandengroep niet gevonden")
    pmsf = tire_forms.pmsf_relevant(ts.type)
    fields = tire_forms.group_fields(
        pmsf=pmsf,
        quantity_label="tire.replace_quantity" if mode == "replace" else "tire.quantity",
        quantity_help="tire.replace_quantity_help" if mode == "replace" else None,
    )
    if mode == "replace":
        fields += [
            Field("replaced_on", "tire.replaced_on", kind="date"),
            Field("note", "tire.replace_note", attrs={"maxlength": "500"}),
        ]
    initial: dict[str, str] = {}
    if group is not None:
        initial = {
            "quantity": str(group.quantity),
            "dot_code": group.dot_code or "",
            "purchase_date": group.purchase_date.isoformat() if group.purchase_date else "",
            "brand": group.brand or "",
            "model": group.model or "",
            "positions": group.positions or "",
            "has_3pmsf": "1" if group.has_3pmsf else "",
        }
    if mode == "replace":
        # Nieuwe banden: vaak hetzelfde merk en model; DOT-code, datum en posities zijn nieuw.
        initial.update({"dot_code": "", "purchase_date": "", "positions": ""})
        initial["replaced_on"] = local_today(v.timezone).isoformat()
    elif mode == "add":
        initial = {"quantity": str(max(1, 4 - ts.tire_count))}
    titles = {
        "add": ("tire.group_add", "tire.group_add"),
        "edit": ("tire.group_edit", "action.save"),
        "replace": ("tire.group_replace", "tire.group_replace"),
    }
    suffix = {
        "add": "/groups/new",
        "edit": f"/groups/{group_id}/edit",
        "replace": f"/groups/{group_id}/replace",
    }[mode]
    title, submit = titles[mode]
    return form_page(
        request,
        title=tr(title),
        intro=tr("tire.replace_intro") if mode == "replace" else None,
        fields=bind(fields, {**initial, **(values or {})}, errors or {}),
        action=f"/vehicles/{vehicle_id}/sets/{set_id}{suffix}",
        cancel=f"/vehicles/{vehicle_id}/sets/{set_id}",
        submit=submit,
        errors=rest,
        status=status,
    )


@router.get("/vehicles/{vehicle_id}/sets/{set_id}/groups/new")
def group_new(request: Request, vehicle_id: int, set_id: int, factory: Factory) -> Response:
    return _group_page(request, factory, vehicle_id, set_id, mode="add")


@router.post("/vehicles/{vehicle_id}/sets/{set_id}/groups/new")
def group_create(
    request: Request, vehicle_id: int, set_id: int, form: FormDep, factory: Factory
) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    with session_scope(factory) as s:
        ts = _vehicle_set(s, vehicle_id, set_id)
    data = tire_forms.parse_group(
        p, relevant_3pmsf=tire_forms.pmsf_relevant(ts.type), default_quantity=1
    )
    group = tire_forms.build_model(p, "", TireGroupIn, data)
    rest: list[str] = []
    if not p.errors and group is not None:
        try:
            with session_scope(factory) as s:
                tire_svc.add_tire_group(s, set_id, group)
            flash(request, tr("flash.group_added"))
            return redirect(f"/vehicles/{vehicle_id}/sets/{set_id}")
        except InvalidOperation as exc:
            rest = [service_error(exc)]
    return _group_page(
        request,
        factory,
        vehicle_id,
        set_id,
        mode="add",
        values=form.values(),
        errors=p.errors,
        rest=rest,
        status=422,
    )


@router.get("/vehicles/{vehicle_id}/sets/{set_id}/groups/{group_id}/edit")
def group_edit(
    request: Request, vehicle_id: int, set_id: int, group_id: int, factory: Factory
) -> Response:
    return _group_page(request, factory, vehicle_id, set_id, mode="edit", group_id=group_id)


@router.post("/vehicles/{vehicle_id}/sets/{set_id}/groups/{group_id}/edit")
def group_update(
    request: Request,
    vehicle_id: int,
    set_id: int,
    group_id: int,
    form: FormDep,
    factory: Factory,
) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    with session_scope(factory) as s:
        ts = _vehicle_set(s, vehicle_id, set_id)
        group = tire_svc.get_tire_group(s, group_id)
    if group.tire_set_id != set_id:
        raise NotFoundError("bandengroep niet gevonden")
    relevant = tire_forms.pmsf_relevant(ts.type)
    data = tire_forms.parse_group(p, relevant_3pmsf=relevant, default_quantity=group.quantity)
    if not relevant:
        data.pop("has_3pmsf")  # niet relevant voor dit seizoen: waarde laten staan
    patch = tire_forms.build_model(p, "", TireGroupPatch, data)
    rest: list[str] = []
    if not p.errors and patch is not None:
        try:
            with session_scope(factory) as s:
                tire_svc.update_tire_group(s, group_id, patch)
            flash(request, tr("flash.saved"))
            return redirect(f"/vehicles/{vehicle_id}/sets/{set_id}")
        except InvalidOperation as exc:
            rest = [service_error(exc)]
    return _group_page(
        request,
        factory,
        vehicle_id,
        set_id,
        mode="edit",
        group_id=group_id,
        values=form.values(),
        errors=p.errors,
        rest=rest,
        status=422,
    )


@router.post("/vehicles/{vehicle_id}/sets/{set_id}/groups/{group_id}/delete")
def group_delete(
    request: Request,
    vehicle_id: int,
    set_id: int,
    group_id: int,
    form: FormDep,
    factory: Factory,
) -> Response:
    tr = views.make_tr(current_locale(request))
    try:
        with session_scope(factory) as s:
            _vehicle_set(s, vehicle_id, set_id)
            if tire_svc.get_tire_group(s, group_id).tire_set_id != set_id:
                raise NotFoundError("bandengroep niet gevonden")
            tire_svc.delete_tire_group(s, group_id)
        flash(request, tr("flash.group_deleted"))
    except InvalidOperation as exc:
        flash(request, service_error(exc), "error")
    return redirect(f"/vehicles/{vehicle_id}/sets/{set_id}")


@router.get("/vehicles/{vehicle_id}/sets/{set_id}/groups/{group_id}/replace")
def group_replace_form(
    request: Request, vehicle_id: int, set_id: int, group_id: int, factory: Factory
) -> Response:
    return _group_page(request, factory, vehicle_id, set_id, mode="replace", group_id=group_id)


@router.post("/vehicles/{vehicle_id}/sets/{set_id}/groups/{group_id}/replace")
def group_replace(
    request: Request,
    vehicle_id: int,
    set_id: int,
    group_id: int,
    form: FormDep,
    factory: Factory,
) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    with session_scope(factory) as s:
        ts = _vehicle_set(s, vehicle_id, set_id)
        group = tire_svc.get_tire_group(s, group_id)
        today = local_today(get_vehicle_or_404(s, vehicle_id).timezone)
    if group.tire_set_id != set_id:
        raise NotFoundError("bandengroep niet gevonden")
    data = tire_forms.parse_group(
        p, relevant_3pmsf=tire_forms.pmsf_relevant(ts.type), default_quantity=group.quantity
    )
    data.update(
        group_id=group_id,
        replaced_on=p.date("replaced_on"),
        note=p.text("note", max_len=500),
    )
    replacement = tire_forms.build_model(p, "", TireReplaceIn, data)
    rest: list[str] = []
    if not p.errors and replacement is not None:
        try:
            with session_scope(factory) as s:
                tire_svc.replace_tires(s, set_id, replacement, today=today)
            flash(request, tr("flash.tires_replaced"))
            return redirect(f"/vehicles/{vehicle_id}/sets/{set_id}")
        except InvalidOperation as exc:
            rest = [service_error(exc)]
    return _group_page(
        request,
        factory,
        vehicle_id,
        set_id,
        mode="replace",
        group_id=group_id,
        values=form.values(),
        errors=p.errors,
        rest=rest,
        status=422,
    )


# --- bandenwissel


def change_fields(tr: Any, sets: list[Any], garages: list[Any]) -> list[Field]:
    return [
        Field("changed_at", "change.date", kind="date", required=True),
        Field(
            "to_set_id",
            "change.to_set",
            kind="select",
            required=True,
            options=tuple((str(s.id), views.set_label(s, tr)) for s in sets),
        ),
        Field(
            "odometer_km",
            "change.odometer",
            help="change.odometer_help",
            attrs={"inputmode": "numeric"},
        ),
        Field(
            "performed_by",
            "change.performed_by",
            kind="select",
            required=True,
            options=opts(ChangeMethod, "method", tr),
        ),
        Field(
            "garage_id",
            "change.garage",
            kind="select",
            options=(("", tr("common.none")), *((str(g.id), g.name) for g in garages)),
        ),
        Field("cost", "change.cost", attrs={"inputmode": "decimal"}),
        Field("notes", "change.notes", kind="textarea"),
    ]


def _change_page(
    request: Request,
    factory: Factory,
    vehicle_id: int,
    values: dict[str, str],
    errors: dict[str, str],
    rest: list[str],
    status: int = 200,
) -> Response:
    tr = views.make_tr(current_locale(request))
    with session_scope(factory) as s:
        v = get_vehicle_or_404(s, vehicle_id)
        sets = [x for x in tire_svc.list_tire_sets(s, vehicle_id) if x.status == TireStatus.STORED]
        garages = garage_svc.list_garages(s)
    base = {
        "changed_at": local_today(v.timezone).isoformat(),
        "performed_by": v.change_method.value,
        "garage_id": str(v.preferred_garage_id or ""),
    }
    fields = bind(change_fields(tr, sets, garages), {**base, **values}, errors)
    if not sets:
        rest = [*rest, tr("change.no_sets")]
    return form_page(
        request,
        title=tr("change.register"),
        fields=fields,
        action=f"/vehicles/{vehicle_id}/changes/new",
        cancel=f"/vehicles/{vehicle_id}",
        submit="change.register",
        errors=rest,
        status=status,
    )


@router.get("/vehicles/{vehicle_id}/changes/new")
def change_new(request: Request, vehicle_id: int, factory: Factory) -> Response:
    return _change_page(request, factory, vehicle_id, {}, {}, [])


@router.post("/vehicles/{vehicle_id}/changes/new")
def change_create(request: Request, vehicle_id: int, form: FormDep, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    with session_scope(factory) as s:
        v = get_vehicle_or_404(s, vehicle_id)
    changed = p.date("changed_at", required=True)
    to_set = p.optional_id("to_set_id")
    if to_set is None and "to_set_id" not in p.errors:
        p.fail("to_set_id", "error.required")
    km = p.integer("odometer_km", minimum=0, maximum=10_000_000)
    by = p.choice("performed_by", ChangeMethod)
    garage = p.optional_id("garage_id")
    cost = p.cents("cost")
    notes = p.text("notes", max_len=2000)
    rest: list[str] = []
    if not p.errors and changed and to_set and by:
        try:
            with session_scope(factory) as s:
                tire_svc.register_tire_change(
                    s,
                    vehicle_id,
                    to_set,
                    changed,
                    odometer_km=km,
                    performed_by=by,
                    garage_id=garage,
                    cost_cents=cost,
                    notes=notes,
                    today=local_today(v.timezone),
                )
            flash(request, tr("flash.change_registered"))
            return redirect(f"/vehicles/{vehicle_id}#history")
        except InvalidOperation as exc:
            rest = [service_error(exc)]
        except NotFoundError as exc:
            rest = [service_error(exc)]
    return _change_page(request, factory, vehicle_id, form.values(), p.errors, rest, 422)


# --------------------------------------------------------------------------- kilometerstanden


def odometer_fields() -> list[Field]:
    return [
        Field("reading_km", "odometer.km", required=True, attrs={"inputmode": "numeric"}),
        Field("recorded_on", "odometer.date", kind="date", required=True),
    ]


@router.post("/vehicles/{vehicle_id}/odometer")
def odometer_add(request: Request, vehicle_id: int, form: FormDep, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    with session_scope(factory) as s:
        v = get_vehicle_or_404(s, vehicle_id)
    km = p.integer("reading_km", required=True, minimum=0, maximum=10_000_000)
    day = p.date("recorded_on", required=True)
    note = p.text("note", max_len=500)
    if not p.errors and km is not None and day is not None:
        when = (
            datetime.now(UTC)
            if day == local_today(v.timezone)
            else datetime.combine(day, time(12), tzinfo=UTC)
        )
        try:
            with session_scope(factory) as s:
                tire_svc.add_odometer_reading(s, vehicle_id, km, when, note)
            flash(request, tr("flash.odometer_added"))
        except InvalidOperation as exc:
            flash(request, service_error(exc), "error")
    else:
        flash(request, " ".join(p.errors.values()), "error")
    return redirect(f"/vehicles/{vehicle_id}#odometer")


@router.post("/vehicles/{vehicle_id}/odometer/{reading_id}/correct")
def odometer_correct(
    request: Request, vehicle_id: int, reading_id: int, form: FormDep, factory: Factory
) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    km = p.integer("reading_km", required=True, minimum=0, maximum=10_000_000)
    note = p.text("note", max_len=500)
    if p.errors or km is None:
        flash(request, " ".join(p.errors.values()), "error")
        return redirect(f"/vehicles/{vehicle_id}#odometer")
    try:
        with session_scope(factory) as s:
            valid = {r.id for r in tire_svc.list_odometer_readings(s, vehicle_id)}
            if reading_id not in valid:
                raise NotFoundError("kilometerstand niet gevonden")
            tire_svc.correct_odometer(s, reading_id, km, note)
        flash(request, tr("flash.odometer_corrected"))
    except InvalidOperation as exc:
        flash(request, service_error(exc), "error")
    return redirect(f"/vehicles/{vehicle_id}#odometer")


# --------------------------------------------------------------------------- afspraken


def appointment_fields(tr: Any, garages: list[Any]) -> list[Field]:
    return [
        Field(
            "garage_id",
            "appointment.garage",
            kind="select",
            required=True,
            options=tuple((str(g.id), g.name) for g in garages),
        ),
        Field(
            "direction",
            "appointment.direction",
            kind="select",
            required=True,
            options=opts(Direction, "direction", tr, [Direction.TO_WINTER, Direction.TO_SUMMER]),
        ),
        Field("period_start", "appointment.period_start", kind="date"),
        Field("period_end", "appointment.period_end", kind="date"),
        Field("notes", "appointment.notes", kind="textarea"),
    ]


@router.post("/vehicles/{vehicle_id}/appointments")
def appointment_create(
    request: Request, vehicle_id: int, form: FormDep, factory: Factory
) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    garage = p.optional_id("garage_id")
    if garage is None and "garage_id" not in p.errors:
        p.fail("garage_id", "error.required")
    direction = p.choice("direction", Direction)
    start, end = p.date("period_start"), p.date("period_end")
    notes = p.text("notes", max_len=2000)
    if not p.errors and garage and direction:
        try:
            with session_scope(factory) as s:
                garage_svc.create_appointment(
                    s,
                    AppointmentIn(
                        vehicle_id=vehicle_id,
                        garage_id=garage,
                        target_direction=direction,
                        target_period_start=start,
                        target_period_end=end,
                        notes=notes,
                    ),
                )
            flash(request, tr("flash.appointment_created"))
        except (InvalidOperation, NotFoundError) as exc:
            if isinstance(exc, NotFoundError) and "garage" not in str(exc):
                raise
            flash(request, service_error(exc), "error")
    else:
        flash(request, " ".join(p.errors.values()) or tr("error.invalid"), "error")
    return redirect(f"/vehicles/{vehicle_id}#appointments")


@router.post("/vehicles/{vehicle_id}/appointments/{appointment_id}/status")
def appointment_status(
    request: Request, vehicle_id: int, appointment_id: int, form: FormDep, factory: Factory
) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    status = p.choice("status", AppointmentStatus)
    at_raw = form.get("appointment_at")
    at_local = parse_local_datetime(at_raw) if at_raw else None
    if at_raw and at_local is None:
        p.fail("appointment_at", "error.invalid")
    if p.errors or status is None:
        flash(request, " ".join(p.errors.values()) or tr("error.invalid"), "error")
        return redirect(f"/vehicles/{vehicle_id}#appointments")
    try:
        with session_scope(factory) as s:
            v = get_vehicle_or_404(s, vehicle_id)
            if garage_svc.get_appointment(s, appointment_id).vehicle_id != vehicle_id:
                raise NotFoundError("afspraak niet gevonden")
            garage_svc.set_appointment_status(
                s,
                appointment_id,
                status,
                to_utc(at_local, v.timezone) if at_local is not None else None,
            )
        flash(request, tr("flash.appointment_updated"))
    except InvalidOperation as exc:
        flash(request, service_error(exc), "error")
    return redirect(f"/vehicles/{vehicle_id}#appointments")


# --------------------------------------------------------------------------- garages


def garage_fields() -> list[Field]:
    return [
        Field("name", "garage.name", required=True, attrs={"maxlength": "120"}),
        Field("address", "garage.address", attrs={"maxlength": "255", "autocomplete": "off"}),
        Field("phone", "garage.phone", kind="tel", attrs={"maxlength": "40"}),
        Field(
            "email",
            "garage.email",
            kind="email",
            help="garage.email_help",
            attrs={"maxlength": "255"},
        ),
        Field(
            "website",
            "garage.website",
            kind="url",
            attrs={"maxlength": "255", "placeholder": "https://"},
        ),
        Field(
            "lead_time_days",
            "garage.lead_time",
            help="garage.lead_time_help",
            value="14",
            attrs={"inputmode": "numeric"},
        ),
        Field("notes", "garage.notes", kind="textarea"),
    ]


def _parse_garage(p: Parser) -> dict[str, Any]:
    email = p.text("email", max_len=255)
    if email is not None and ("@" not in email or " " in email):
        p.fail("email")
    lead = p.integer("lead_time_days", minimum=0, maximum=365)
    website = p.text("website", max_len=255)
    if website is not None and not website.lower().startswith(("http://", "https://")):
        p.fail("website", "error.url")
    return {
        "name": p.text("name", required=True, max_len=120),
        "address": p.text("address"),
        "phone": p.text("phone", max_len=40),
        "email": email,
        "website": website,
        "notes": p.text("notes", max_len=2000),
        "lead_time_days": lead if lead is not None else 14,
    }


@router.get("/garages")
def garages_list(request: Request, factory: Factory) -> Response:
    with session_scope(factory) as s:
        garages = garage_svc.list_garages(s)
    return render(request, "garages.html", {"garages": garages}, nav="garages")


@router.get("/garages/new")
def garage_new(request: Request) -> Response:
    tr = views.make_tr(current_locale(request))
    return form_page(
        request,
        title=tr("garage.new"),
        fields=bind(garage_fields(), {}, {}),
        action="/garages/new",
        cancel="/garages",
        submit="garage.create",
        nav="garages",
    )


@router.post("/garages/new")
def garage_create(request: Request, form: FormDep, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    raw = _parse_garage(p)
    rest: list[str] = []
    if not p.errors:
        try:
            with session_scope(factory) as s:
                garage_svc.create_garage(s, GarageIn(**raw))
            flash(request, tr("flash.garage_created"))
            return redirect("/garages")
        except ValidationError as exc:
            rest = p.apply_validation_error(exc, list(raw))
    return form_page(
        request,
        title=tr("garage.new"),
        fields=bind(garage_fields(), form.values(), p.errors),
        action="/garages/new",
        cancel="/garages",
        submit="garage.create",
        nav="garages",
        errors=rest,
        status=422,
    )


@router.get("/garages/{garage_id}/edit")
def garage_edit(request: Request, garage_id: int, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    with session_scope(factory) as s:
        g = garage_svc.get_garage(s, garage_id)
    values = {
        "name": g.name,
        "address": g.address or "",
        "phone": g.phone or "",
        "email": g.email or "",
        "website": g.website or "",
        "notes": g.notes or "",
        "lead_time_days": str(g.lead_time_days),
    }
    return form_page(
        request,
        title=tr("garage.edit"),
        fields=bind(garage_fields(), values, {}),
        action=f"/garages/{garage_id}/edit",
        cancel="/garages",
        nav="garages",
    )


@router.post("/garages/{garage_id}/edit")
def garage_update(request: Request, garage_id: int, form: FormDep, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    p = Parser(form, tr)
    raw = _parse_garage(p)
    rest: list[str] = []
    if not p.errors:
        try:
            with session_scope(factory) as s:
                garage_svc.update_garage(s, garage_id, GaragePatch(**raw))
            flash(request, tr("flash.saved"))
            return redirect("/garages")
        except ValidationError as exc:
            rest = p.apply_validation_error(exc, list(raw))
        except InvalidOperation as exc:
            rest = [service_error(exc)]
    return form_page(
        request,
        title=tr("garage.edit"),
        fields=bind(garage_fields(), form.values(), p.errors),
        action=f"/garages/{garage_id}/edit",
        cancel="/garages",
        nav="garages",
        errors=rest,
        status=422,
    )


@router.post("/garages/{garage_id}/delete")
def garage_delete(request: Request, garage_id: int, form: FormDep, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    try:
        with session_scope(factory) as s:
            garage_svc.delete_garage(s, garage_id)
        flash(request, tr("flash.garage_deleted"))
    except InvalidOperation as exc:
        flash(request, service_error(exc), "error")
    return redirect("/garages")


# --------------------------------------------------------------------------- instellingen


def _settings_context(
    request: Request,
    factory: sessionmaker[Session],
    forecasts: Any,
    compare_location: int | None,
    new_token: str | None = None,
) -> dict[str, Any]:
    locale = current_locale(request)
    tr = views.make_tr(locale)
    infos = forecasts.provider_infos()
    providers = [
        {
            "info": i,
            "status": tr(i.status_detail) if i.status_detail else None,
            "days": max(1, i.horizon_hours // 24),
            "default": i.id == forecasts.default_provider,
        }
        for i in infos
    ]
    with session_scope(factory) as s:
        locations = [
            {
                "id": loc.id,
                "name": loc.name,
                "lat": loc.latitude,
                "lon": loc.longitude,
                "vehicles": n,
            }
            for loc, n in s.execute(
                select(Location, func.count(Vehicle.id))
                .outerjoin(Vehicle, Vehicle.location_id == Location.id)
                .group_by(Location.id)
                .order_by(Location.id)
            ).all()
        ]
        tokens = [
            {
                "name": t.name,
                "created": format_date(t.created_at, locale),
                "used": format_date(t.last_used_at, locale) if t.last_used_at else "",
            }
            for t in s.scalars(
                select(ApiToken).where(ApiToken.revoked_at.is_(None)).order_by(ApiToken.id)
            )
        ]
    comparison = None
    if compare_location is not None:
        loc = next((x for x in locations if x["id"] == compare_location), None)
        if loc is not None:
            comparison = _compare(forecasts, loc, infos, locale)
    return {
        "providers": providers,
        "default_provider": forecasts.default_provider,
        "configured_options": [
            (p["info"].id, p["info"].name) for p in providers if p["info"].configured
        ],
        "locations": locations,
        "tokens": tokens,
        "comparison": comparison,
        "compare_location": compare_location,
        "new_token": new_token,
    }


def _compare(forecasts: Any, loc: dict, infos: list[Any], locale: str) -> dict:
    tr = views.make_tr(locale)
    fcs, failed = [], []
    for info in infos:
        if not info.configured:
            continue
        try:
            fcs.append(forecasts.get_forecast(loc["lat"], loc["lon"], info.id))
        except ProviderError:
            failed.append(info.name)
    names = {i.id: i.name for i in infos}
    with_data = [f for f in fcs if f.hourly]
    days = compare_forecasts(with_data, DEFAULT_TZ)[:14]
    provider_ids = [f.provider for f in with_data]
    rows = []
    for d in days:
        cells = []
        for pid in provider_ids:
            pd = d.providers.get(pid)
            cells.append(
                None
                if pd is None
                else {
                    "min": pd.temp_min_c,
                    "max": pd.temp_max_c,
                    "precip": pd.precip_mm,
                }
            )
        rows.append(
            {
                "day": d.day,
                "cells": cells,
                "min_spread": d.temp_min_spread_c,
                "max_spread": d.temp_max_spread_c,
                "precip_spread": d.precip_spread_mm,
            }
        )
    return {
        "location": loc["name"],
        "providers": [names.get(pid, pid) for pid in provider_ids],
        "rows": rows,
        "failed": failed,
        "label": tr("compare.label"),
    }


@router.get("/settings")
def settings_page(
    request: Request, factory: Factory, forecasts: Forecasts, location: int | None = None
) -> Response:
    ctx = _settings_context(request, factory, forecasts, location)
    return render(request, "settings.html", ctx, nav="settings")


@router.post("/settings/provider")
def settings_provider(
    request: Request, form: FormDep, factory: Factory, forecasts: Forecasts
) -> Response:
    tr = views.make_tr(current_locale(request))
    choice = form.get("provider")
    infos = {i.id: i for i in forecasts.provider_infos()}
    info = infos.get(choice)
    if info is None or not info.configured:
        flash(request, tr("settings.provider_unavailable"), "error")
        return redirect("/settings")
    with session_scope(factory) as s:
        s.merge(AppSetting(key=DEFAULT_PROVIDER_KEY, value=choice))
    forecasts.set_default_provider(choice)
    flash(request, tr("flash.provider_saved", name=info.name))
    return redirect("/settings")


@router.post("/settings/tokens")
def settings_token_create(
    request: Request, form: FormDep, factory: Factory, forecasts: Forecasts
) -> Response:
    name = form.get("token_name")
    token: str | None = None
    try:
        with session_scope(factory) as s:
            token = auth.create_api_token(s, name)
    except auth.AuthError as exc:
        flash(request, str(exc), "error")
        return redirect("/settings#tokens")
    ctx = _settings_context(request, factory, forecasts, None, new_token=token)
    ctx["token_name"] = name
    response = render(request, "settings.html", ctx, nav="settings")
    response.headers["Cache-Control"] = "no-store"
    log.info("api_token_created")
    return response


@router.post("/settings/tokens/revoke")
def settings_token_revoke(request: Request, form: FormDep, factory: Factory) -> Response:
    tr = views.make_tr(current_locale(request))
    try:
        with session_scope(factory) as s:
            auth.revoke_api_token(s, form.get("token_name"))
        flash(request, tr("flash.token_revoked"))
    except auth.AuthError as exc:
        flash(request, str(exc), "error")
    return redirect("/settings#tokens")
