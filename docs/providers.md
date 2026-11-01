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

## Geocoderen

Bij het invullen van een locatie kan de webinterface een adres, postcode of plaats omzetten naar coördinaten (`GET /api/v1/geocode`, zie [api.md](api.md)). Dit is geen weerbron en staat los van de providers hierboven.

- **Dienst:** een Nominatim-compatibele API, standaard `https://nominatim.openstreetmap.org` (`WISSELWEER_GEOCODER_URL`). Alleen `https://`; `http://` mag alleen voor `localhost` of een loopback-adres. Uitzetten kan met `off` (een lege omgevingsvariabele telt als "niet gezet" en geeft dus de standaard; in code of `Settings(geocoder_url="")` betekent leeg wel uit).
- **Voorwaarde:** `WISSELWEER_CONTACT` moet gezet zijn. Het komt, net als bij MET Norway, in de User-Agent (`Wisselweer/<versie> (+https://wisselweer.nl; <contact>)`); zonder contact is geocoderen uitgeschakeld (`503 geocoder_not_configured`, zoekveld verborgen).
- **Verzoek:** `GET <URL>/search?q=…&format=jsonv2&limit=5&addressdetails=0&accept-language=<taal>`. De taal is de interfacetaal van de gebruiker (sessie), of de optionele `lang`-parameter.
- **Gebruiksregels van Nominatim** (<https://operations.osmfoundation.org/policies/nominatim/>): herkenbare User-Agent, maximaal 1 verzoek per seconde, resultaten cachen, geen zware of geautomatiseerde bulkzoekopdrachten, bronvermelding "© OpenStreetMap-bijdragers" (ODbL, <https://www.openstreetmap.org/copyright>). De app houdt zich daaraan met een proces-brede limiet van 1 upstream-verzoek per seconde (een verzoek wacht maximaal 3 s op zijn beurt, daarna `429` met `Retry-After`), een in-memory cache van 24 uur (genormaliseerde zoektekst + taal, max. 500 items; foutantwoorden worden niet gecachet) en de vermelding onder het zoekveld. De openbare instantie is bedoeld voor licht, interactief gebruik zoals hier; voor veel gebruikers of eigen automatisering: host zelf.
- **Eigen instantie:** zet `WISSELWEER_GEOCODER_URL` op je eigen Nominatim (<https://nominatim.org/release-docs/latest/admin/Installation/>), bijvoorbeeld `http://127.0.0.1:8088` op dezelfde machine of `https://geocoder.example.invalid`. Elke Nominatim-compatibele `/search`-API met `jsonv2` werkt.
- **Privacy:** de zoektekst gaat alleen op het moment dat iemand op "Zoek coördinaten" klikt via de server naar de geocoder (met het IP van de server en het contactgegeven in de User-Agent; de browser spreekt de geocoder nooit rechtstreeks aan). De zoektekst wordt niet opgeslagen en niet gelogd (query's staan niet in de accesslog en de `httpx`-logger staat op WARNING). Alleen de door de gebruiker gekozen, op 3 decimalen (ca. 100 m) afgeronde coördinaten komen in de locatie. De knop "Gebruik mijn locatie" gebruikt `navigator.geolocation` van de browser (alleen via https of localhost, na toestemming) en stuurt niets naar een dienst; de `Permissions-Policy` staat `geolocation` alleen voor de eigen origin toe.
- **Fouten:** upstream-fout, time-out, onverwachte status of onbruikbaar antwoord geeft `502 geocoder_unavailable` zonder details; een leeg resultaat is `200 []`.

## Cache, service en vergelijking
- `ForecastCache`: vers tot `Expires` (zonder: 30 min), daarna conditioneel ophalen (304 verlengt). Bij fouten wordt cache tot `max_stale_hours` (24) teruggegeven met `is_stale=True`; `retry_after` wordt gerespecteerd. Per sleutel (provider, lat4, lon4) één lock: meerdere voertuigen delen één request. De cache staat in SQLite (tabel `forecast_cache`, `storage/cache_backend.py`), zodat die een herstart overleeft; `InMemoryBackend` (in `weather/cache.py`) wordt alleen in tests gebruikt.
- `compare_forecasts` toont per dag min/max/neerslag per provider en de spreiding. Alleen diagnostisch; combineert niets.
