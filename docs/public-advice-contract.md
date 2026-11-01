# Publiek adviescontract — `advice.json` (schema_version 1)

Enige koppeling tussen de privé-app en elke publieke site of andere afnemer (eigen site, Home Assistant). Bevat uitsluitend deze velden (allowlist, `extra="forbid"`).

| Veld | Type | Betekenis |
|---|---|---|
| `schema_version` | int (1) | Contractversie |
| `country` | `"NL"` | Land |
| `locale` | `"nl-NL"` | Taal van de teksten |
| `next_season` | `"winter"` \| `"summer"` | Richting van de vraag |
| `heading` | str | "Wanneer winterbanden?" / "Wanneer zomerbanden?" |
| `status` | `KEEP_CURRENT` \| `PREPARE_CHANGE` \| `CHANGE_RECOMMENDED` \| `REGIONAL_DIFFERENCES` \| `INSUFFICIENT_DATA` | Landelijke status |
| `status_label` | str | Korte NL-tekst bij de status |
| `summary` | str | 1–2 zinnen uitleg |
| `recommended_date` | ISO-datum \| null | Alleen als alle eensgezinde regio's dezelfde concrete datum onderbouwen |
| `recommended_period` | `{start, end}` (ISO-datums) \| null | Periode, alleen als onderbouwd |
| `regional_variation` | bool | Regio's verschillen |
| `regions` | lijst `{name, status}` | Referentielocaties (plaatsnamen, publiek) |
| `forecast_until` | ISO-datum \| null | Einde van de gebruikte voorspellingshorizon |
| `outlook` | lijst `{date, temp_min_c, temp_max_c, frost_night, snow_possible, kind}` \| ontbreekt/null | Optionele vooruitblik tot 14 dagen (zie hieronder) |
| `generated_at` | ISO-datetime (UTC, `Z`) | Moment van genereren |
| `stale_after` | ISO-datetime (UTC, `Z`) | Daarna toont de site een "verouderd"-melding |
| `source` | `{name, attribution, license_url}` | Weerbron + verplichte bronvermelding |
| `rules_version` | str | Versie adviesregels |
| `countries` | lijst `PublicCountry` \| ontbreekt | Optionele winterbandenregels per land (zie hieronder) |
| `countries_disclaimer` | str \| ontbreekt | Verplichte disclaimer bij `countries` |

Regels:
- Geen voertuigen, kentekens, garages, contactgegevens, coördinaten van gebruikers of instellingen.
- Geen datums die niet door voorspellingsdata onderbouwd zijn.
- Status `REGIONAL_DIFFERENCES` ⇒ summary: "De omstandigheden verschillen per regio. Er is nog geen eenduidig landelijk wisselmoment."
- Landelijk advies is indicatief en vervangt geen lokale gladheidswaarschuwing.

## Optioneel veld `outlook` (additief, `schema_version` blijft 1)
- Per dag: `date` (lokale dag, Europe/Amsterdam), `temp_min_c`/`temp_max_c` (°C, 1 decimaal, mogen null zijn), `frost_night` (minimumtemperatuur in de nacht 00-08 en 20-24 uur ≤ 0 °C), `snow_possible` (sneeuw/natte sneeuw in de verwachting of `snow_cm` > 0; `false` als de bron dat niet levert) en `kind`: `concrete` (dag 1-7) of `trend` (dag 8-14, indicatief).
- Alleen dagen die de weerbron daadwerkelijk dekt (MET Norway ca. 9-10 dagen); er worden nooit dagen bijgeschat. Het veld mag ontbreken of null zijn; de site verbergt dan het blok.
- Gebaseerd op de verwachting van een enkel referentiepunt, De Bilt (eerste locatie in de lijst). Dat is niet representatief voor heel Nederland en wordt op de site zo benoemd.
- Voorbeeld: [examples/public-advice.json](examples/public-advice.json).

## Optioneel veld `countries` (additief, `schema_version` blijft 1)
Alleen aanwezig als de publicatie draait met `WISSELWEER_PUBLISH_COUNTRIES=true`; anders ontbreken `countries` en `countries_disclaimer` volledig in het bestand. Achtergrond en onderhoud: [regulations.md](regulations.md). Regelgeving staat los van het meteorologische advies: de landenregels beïnvloeden `status`, `summary` of datums nooit.

`PublicCountry` (allowlist, `extra="forbid"`):

| Veld | Type | Betekenis |
|---|---|---|
| `code` | str | ISO-3166 alpha-2 (bv. `DE`) |
| `name` | str | Landnaam (NL) |
| `rule_types` | lijst van `situational` \| `period` \| `area_or_signage` \| `none` | Soort regel; een land kan er meerdere hebben |
| `period_label` | str \| null | Bv. "1 november – 15 april" |
| `in_period` | bool \| null | Of vandaag (Europe/Amsterdam) binnen die datums valt; null zonder periode. Zegt niets over of de plicht op de weg geldt |
| `conditions_text` | str \| null | Voorwaarden waaronder de regel geldt |
| `tires_text` | str | Welke banden |
| `min_tread_mm` | number \| null | Profielminimum |
| `alternatives_text` | str \| null | Kettingen, sneeuwsokken e.d. |
| `notes_text` | str \| null | Onzekerheden en bijzonderheden |
| `sources` | lijst `{title, url}` | Bronnen (https), minimaal één |
| `checked_on` | ISO-datum | Laatst gecontroleerd |
| `confidence` | `high` \| `medium` \| `low` | Betrouwbaarheid van de gegevens |
| `weather` | object \| null | Alleen bij `situational`: verwachte omstandigheden (hieronder) |

`weather`: `status` (`winter_conditions_expected` = sneeuw of gladheid verwacht, `frost_possible` = alleen vorst, `none_expected`, `unknown` = geen bruikbare verwachting), `partial` (bool; niet voor alle referentielocaties was data), `locations` (lijst `{name, mountain, frost, snow, icy}`, alleen plaatsen met data) en `window_hours` (72).

Regels:
- Geen enkel veld of statusnaam zegt dat een plicht nu geldt. Een voorspelling is geen vaststelling: wat geldt hangt af van de werkelijke weg- en weersomstandigheden ter plaatse. De site toont `countries_disclaimer` bij het blok.
- Bedragen van sancties worden bewust niet gepubliceerd.
- De referentieplaatsen zijn publiek en benaderd; er zijn geen gebruikerslocaties.
