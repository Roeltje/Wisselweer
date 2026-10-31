# Publiek adviescontract — `advice.json` (schema_version 1)

Enige koppeling tussen de privé-app en de publieke site. Bevat uitsluitend deze velden (allowlist, `extra="forbid"`).

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
| `generated_at` | ISO-datetime (UTC, `Z`) | Moment van genereren |
| `stale_after` | ISO-datetime (UTC, `Z`) | Daarna toont de site een "verouderd"-melding |
| `source` | `{name, attribution, license_url}` | Weerbron + verplichte bronvermelding |
| `rules_version` | str | Versie adviesregels |

Regels:
- Geen voertuigen, kentekens, garages, contactgegevens, coördinaten van gebruikers of instellingen.
- Geen datums die niet door voorspellingsdata onderbouwd zijn.
- Status `REGIONAL_DIFFERENCES` ⇒ summary: "De omstandigheden verschillen per regio. Er is nog geen eenduidig landelijk wisselmoment."
- Landelijk advies is indicatief en vervangt geen lokale gladheidswaarschuwing.
