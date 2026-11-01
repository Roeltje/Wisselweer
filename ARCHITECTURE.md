# Wisselweer — Architectuur

*Het juiste moment om te wisselen.*

Dit document is het bindende contract voor alle code in deze repository. Afwijken alleen na aanpassing van dit document.

## 1. Productoppervlakken

| Oppervlak | Wat | Data |
|---|---|---|
| **Engine** (`wisselweer.core`) | Pure, uitlegbare adviesberekening | Alleen aangeleverde objecten |
| **Self-hosted app** (`wisselweer.api` + `wisselweer.web`) | Beheer van voertuigen, banden, garages, advies | Lokale SQLite, privé |
| **Publieke site (apart, niet in deze repo)** | Statische site van wisselweer.nl die alleen `advice.json` leest | Uitsluitend allowlisted publieke velden |

De publieke site wordt apart onderhouden. Deze repo publiceert `advice.json` volgens [docs/public-advice-contract.md](docs/public-advice-contract.md); het bestand is ook bruikbaar voor bijvoorbeeld Home Assistant of een dashboard. Een publieke site heeft **nooit** een netwerkpad naar de privé-app: de privé-app *duwt* `advice.json` naar een map of via SFTP naar de webserver.

## 2. Stack

Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, SQLite, httpx, Jinja2 (server-rendered UI, minimale vanilla JS), pytest + respx. Geen Redis/Postgres/Node-build.

## 3. Repository-indeling

```
pyproject.toml            # package `wisselweer`, src-layout
src/wisselweer/
  core/                   # PURE: geen FastAPI/SQLAlchemy/httpx/IO
    models.py             # Forecast, HourlyPoint, TireType, DrivingProfile, Advice, Warning...
    config.py             # EngineConfig: alle drempels (heuristieken, configureerbaar)
    engine.py             # evaluate(input) -> Advice
    stability.py          # hysterese tussen opeenvolgende adviezen
    rules_version.py
  weather/
    base.py               # ForecastProvider-protocol + ProviderInfo (variabelen, horizon, licentie)
    metno.py  openmeteo.py  brightsky.py  knmi.py
    cache.py              # per (provider, afgeronde locatie); Expires/Last-Modified/304; stale-markering
    registry.py           # providerkeuze + 'niet geconfigureerd'-status
    compare.py            # diagnostische modelvergelijking (NIET combineren)
  observations/
    base.py               # ObservationProvider-protocol + Observation-model
    wunderground.py  knmi.py
  storage/
    db.py  orm.py         # SQLAlchemy-modellen
    migrations/           # Alembic
  vehicles/ tires/ garages/   # services (business-logica op ORM, transacties)
  api/
    app.py                # create_app(); routers onder /api/v1
    auth.py               # sessie + CSRF + optionele API-token
    routers/*.py
  web/
    routes.py templates/ static/
  publisher/
    national.py           # NationalAdviceService (referentielocaties)
    public_schema.py      # PublicAdvice (allowlist, extra='forbid')
    publish.py            # temp -> valideren -> os.replace; optioneel SFTP
  i18n/
    locales/{nl-NL,nl-BE,en,de-DE}.json
    regulations/          # (leeg) toekomstige landenregels met bron/geldigheid
  settings.py             # pydantic-settings uit env (.env)
  cli.py                  # `wisselweer serve|publish|migrate|create-admin|reset-password|create-api-token|revoke-api-token|backtest`
  backtest.py             # replay van forecast-snapshots (zie docs/backtesting.md)
branding/                 # logo.svg, logo-mono.svg, favicon.svg, PNG's
deploy/                   # systemd-units, installatiescripts
Dockerfile  compose.yaml  .env.example
docs/                     # api.md, providers.md, advice-rules.md, install-*.md, testing.md
tests/                    # unit/ integration/ security/ fixtures/
```

## 4. De engine (`core`)

**Invoer** `AdviceInput`: `forecast: Forecast | None`, `mounted: TireType | None`, `profile: DrivingProfile`, `now: datetime (aware)`, `previous: Advice | None`, `lead_time_days: int`, `config: EngineConfig`.

**Uitvoer** `Advice`: `direction` (`TO_WINTER` / `TO_SUMMER` / `NONE`), `heading` (i18n-sleutel), `status` (`KEEP_CURRENT`, `PREPARE_CHANGE`, `CHANGE_RECOMMENDED`, `INSUFFICIENT_DATA`), `warnings[]` (`POSSIBLE_FROST`, `POSSIBLE_SNOW`, `POSSIBLE_ICY_CONDITIONS`, `FORECAST_UNAVAILABLE`, `FORECAST_STALE`) elk met tijdvenster, `recommended_date: date | None`, `recommended_period: (date, date) | None`, `plan_appointment_by: date | None`, `horizon_until`, `reasons[]` (i18n-sleutel + parameters), `uncertainties[]`, `rules_version`.

**Principes**
- Richting volgt de **gemonteerde set**, niet de kalender. Vierseizoenen ⇒ `direction=NONE`, alleen waarschuwingen.
- **Asymmetrie**: naar winter reageert sneller (veiligheid); naar zomer vereist langere warme bevestiging + seizoensvenster (bijv. niet vóór 1 maart) + geen vorst in de horizon.
- 7 °C is **context**, geen grens. Alle drempels in `EngineConfig`, gedocumenteerd als ongevalideerde heuristieken.
- Horizonnen: 0–72 u waarschuwingen; dag 4–7 concrete advies; 8–14 trend (alleen als de provider het levert); daarbuiten geen datum.
- Exacte datum alleen als de omslag binnen dag 1–7 valt en minimaal `confirm_days` aaneengesloten bevestigd wordt; anders periode of `None` ("Nog geen betrouwbare wisseldatum beschikbaar.").
- Rijmomenten: temperatuur/neerslag gewogen naar uren waarin het voertuig volgens profiel rijdt (tijdzone-correct, DST-veilig via `zoneinfo`).
- **Stabiliteit**: hysterese t.o.v. `previous` — status mag pas verlagen na `n` bevestigingen; waarschuwingen zijn nooit gedempt.
- Ontbrekende variabelen ⇒ expliciet in `uncertainties`; nooit invullen. Geen bruikbare forecast ⇒ `INSUFFICIENT_DATA` + `FORECAST_UNAVAILABLE`/`FORECAST_STALE`.
- Geen percentages of gladheidskansen.

## 5. Weer

`ForecastProvider.fetch(lat, lon) -> Forecast` en `info() -> ProviderInfo(name, attribution, license_url, variables, horizon_hours, commercial_use_ok, needs_credentials, configured)`.
- **MET Norway** (standaard): `User-Agent` verplicht uit config (`WISSELWEER_CONTACT`), anders `configured=False`. Coördinaten max. 4 decimalen. Respecteer `Expires`/`If-Modified-Since`/304, 429/403.
- **Open-Meteo**: `commercial_use_ok=False` voor de gratis host; als `WISSELWEER_COMMERCIAL=true` en geen eigen `OPENMETEO_BASE_URL`/key ⇒ weigeren.
- **Bright Sky (DWD)**: forecast + observaties, open data.
- **KNMI Open Data**: vereist API-key; zonder key `configured=False`. MVP: alleen observaties (EDR, 10-min). Een KNMI-forecast is niet beschikbaar (HARMONIE alleen als GRIB/NetCDF): `KnmiForecastProvider` meldt `configured=False`.
- **Weather Underground PWS**: observatieprovider; station-ID + API-key. Adapter bestaat; het advies gebruikt nog geen waarnemingen.
- Cache: SQLite-tabel `forecast_cache` per `(provider, lat4, lon4)`; meerdere auto's op dezelfde locatie delen één fetch; fallback naar oudere data tot `max_stale_hours`, gemarkeerd.
- `compare.py`: toont verschillen tussen providers ter diagnose; combineert niets.

## 6. Data (SQLite)

`vehicle`, `tire_set`, `tread_measurement`, `odometer_reading`, `tire_change`, `garage`, `appointment`, `location`, `forecast_cache`, `forecast_snapshot` (één per provider/locatie/fetch, voor backtests), `advice_snapshot` (voor stabiliteit + backtest; `invalidated_at` wordt gezet bij een bandenwissel zodat de hysterese reset maar de rij bewaard blijft), `app_setting`, `admin_user`, `api_token` (alleen SHA-256-hash).
- Max. één `tire_set.status='mounted'` per voertuig (partial unique index).
- Bandenwissel = één transactie (historie, statussen, km, advies-snapshot ongeldig).
- Km per set = som van verschillen tussen opeenvolgende **geldige** meetpunten tijdens montage; correcties via `superseded_by`, nooit verwijderen.

## 7. Beveiliging

- Bindt standaard op `127.0.0.1`. Docker publiceert `127.0.0.1:8000`.
- Eén lokale beheerder (`wisselweer create-admin`), wachtwoord met `hashlib.scrypt`; sessiecookie `HttpOnly`, `SameSite=Strict`, `Secure` configureerbaar; CSRF-token op alle muterende requests; optionele API-token (Bearer) voor Home Assistant.
- `/docs` en `/openapi.json` alleen na login. Geen debug, generieke foutmeldingen, geen PII in logs.
- Publiek JSON via `PublicAdvice` (Pydantic, `extra='forbid'`), gebouwd uit `NationalAdviceService` — nooit uit ORM-objecten. Test controleert dat kentekens/e-mail/namen niet in output staan.
- Secrets alleen via env; `.env` staat in `.gitignore`.

## 8. Publicatie

`wisselweer publish` (cron/systemd-timer, of de interne planner via `WISSELWEER_PUBLISH_INTERVAL_HOURS`): referentielocaties (De Bilt, Groningen, Vlissingen, Maastricht, Den Helder, Twente, Arnhem — configureerbaar) → per locatie engine met `mounted=SUMMER` resp. `WINTER` afhankelijk van seizoensrichting → samenvoegen (bij onenigheid tussen regio's status `REGIONAL_DIFFERENCES`) → `PublicAdvice` → temp-bestand → valideren → `os.replace`. Optioneel SFTP met beperkte deploy-user (alleen `advice.json`).

## 9. i18n

Alle UI-teksten en reden-sleutels via `i18n/locales/*.json`. Onderscheid taal / land / tijdzone / locatie / gebruikslanden / regelgeving. Regelgeving staat los van het meteorologische advies: de engine kent geen landenregels. `wisselweer.regulations` bevat informatieve winterbandenregels per land (data in `i18n/regulations/winter_tires.json`, met bron, `checked_on` en betrouwbaarheid; bewust zonder boetebedragen) en een pure weercheck voor situationele plichten die dezelfde gladheidsdetectie hergebruikt als de engine. Optioneel (`WISSELWEER_PUBLISH_COUNTRIES`) gaat dit als additief veld `countries` mee in `advice.json`. Het is geen juridisch advies; zie [docs/regulations.md](docs/regulations.md).

## 10. Branding

Petrol `#0F4C5C`, donker petrol `#0A3540`, winterblauw `#5BA4CF`, warm oranje `#F28C28`, gebroken wit `#F7F5F0`. Logo: band met profiel, velg en twee wisselpijlen (`branding/logo.svg`). Systeemfonts, `prefers-color-scheme`.
