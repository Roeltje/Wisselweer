# Weer- en waarnemingsbronnen

Alle providers zijn synchroon (`httpx.Client`, time-out 15 s, HTTPS), leveren UTC-tijden en
laten niet-geleverde variabelen `None` (`available_variables` bevat alleen echt geleverde velden).
Coördinaten worden op 4 decimalen afgerond. Foutmeldingen en logs bevatten nooit API-keys of URL's.
Bij keys in de query-string (Open-Meteo, Weather Underground) wordt de `httpx`-logger op WARNING gezet.

Fouten: 429 → `ProviderRateLimited` (met `Retry-After`), 5xx/netwerk/401/403 → `ProviderUnavailable`,
ontbrekende credentials → `info().configured=False` en `ProviderNotConfigured` bij ophalen.

## MET Norway (`metno`, standaard)
- Locationforecast 2.0 `complete`; horizon ~9–10 dagen (uurstappen tot ~60 u, daarna 6-uursstappen: geen uurneerslag).
- Variabelen: temperatuur, dauwpunt, vochtigheid, wind, neerslag (per uur), neerslagtype (uit `symbol_code`). Geen sneeuwhoeveelheid, geen neerslagkans.
- Licentie: CC BY 4.0 (<https://api.met.no/doc/License>). Bronvermelding: "Weerdata: MET Norway (CC BY 4.0)". Commercieel gebruik toegestaan.
- Configuratie: `contact` verplicht (komt in de User-Agent). Zonder: `provider.missing_contact`.
- Respecteert `Expires`, `Last-Modified`/`If-Modified-Since` (304).

## Open-Meteo (`openmeteo`)
- Horizon 16 dagen. Variabelen: temperatuur, dauwpunt, vochtigheid, neerslag, neerslagkans, sneeuwval, sneeuwdikte, weercode (WMO → neerslagtype), wind (m/s).
- Licentie CC BY 4.0. Bronvermelding: "Weerdata: Open-Meteo.com (CC BY 4.0)".
- De gratis host (`api.open-meteo.com`) is niet-commercieel. Met `commercial=True` zonder eigen `base_url` of API-key: `configured=False`, `provider.openmeteo_noncommercial`.
- Configuratie: `openmeteo_base_url`, `openmeteo_api_key`, `commercial`.

## Bright Sky / DWD (`brightsky`, `brightsky_obs`)
- Verwachting (DWD MOSMIX, ~10 dagen) via `/weather`; actuele waarneming via `/current_weather`. Wind komt in km/u en wordt omgerekend naar m/s; neerslag in de waarneming is mm/10 min en wordt ×6 naar mm/u.
- Variabelen: temperatuur, dauwpunt, vochtigheid, neerslag, neerslagkans, wind, neerslagtype (uit `condition`). Geen sneeuwhoeveelheid.
- Open data van het DWD; bronvermelding "Weerdata: Deutscher Wetterdienst (DWD), via Bright Sky". De publieke Bright Sky-instantie is bedoeld voor niet-commercieel gebruik (`commercial_use_ok=False`; zelf hosten kan; controleer de actuele voorwaarden).
- Geen credentials. Dekking: Duitsland en omgeving; modelkwaliteit voor Nederland is niet gevalideerd.

## KNMI Data Platform (`knmi`, `knmi_forecast`)
- Waarnemingen: EDR API (`https://api.dataplatform.knmi.nl/edr/v1`), collectie `10-minute-in-situ-meteorological-observations`, CoverageJSON, API-key in de `Authorization`-header (zonder prefix). Station-ID verplicht (`knmi_station_id`).
- Gevraagde parameters: `ta`, `td`, `rh`, `ff`, `pp`, `rg`. **Niet tegen de live API geverifieerd**: alleen `ta` en `rh` staan in KNMI's voorbeeld; de overige namen/eenheden zijn aannames. De parser is defensief (ontbrekend → `None`).
- Verwachting (HARMONIE): niet beschikbaar als JSON/EDR; KNMI biedt modeldata als GRIB/NetCDF-bestanden (zware afhankelijkheden, buiten MVP). `KnmiForecastProvider` meldt daarom `configured=False`, `provider.knmi_forecast_not_available`. De EDR-collectie `wins50` is windmodeldata en geen algemene verwachting.
- Licentie CC BY 4.0; bronvermelding "Weerdata: KNMI (CC BY 4.0)". Key aanvragen via de KNMI API Catalog.

## Weather Underground PWS (`wunderground`)
- Eigen station, `https://api.weather.com/v2/pws/observations/current` (`format=json`, `units=m`; wind km/u → m/s).
- Configuratie: `wu_station_id` en `wu_api_key`; zonder: `configured=False`. Aanvullend, nooit automatisch een forecastcorrectie. Voorwaarden van Weather Underground beperken commercieel gebruik (`commercial_use_ok=False`).

## Cache, service en vergelijking
- `ForecastCache`: vers tot `Expires` (zonder: 30 min), daarna conditioneel ophalen (304 verlengt). Bij fouten wordt cache tot `max_stale_hours` (24) teruggegeven met `is_stale=True`; `retry_after` wordt gerespecteerd. Per sleutel (provider, lat4, lon4) één lock: meerdere voertuigen delen één request. De cache staat in SQLite (tabel `forecast_cache`, `storage/cache_backend.py`), zodat die een herstart overleeft; `InMemoryBackend` (in `weather/cache.py`) wordt alleen in tests gebruikt.
- `compare_forecasts` toont per dag min/max/neerslag per provider en de spreiding. Alleen diagnostisch; combineert niets.
