# Adviesregels (rules_version 0.1.0)

> **Alle drempels hieronder zijn ONGEVALIDEERDE HEURISTIEKEN.** Ze zijn niet gekalibreerd aan bandenprestaties, ongevallen- of klimaatdata. Ze zijn bedoeld als configureerbare startwaarden (`EngineConfig`) en worden pas aangescherpt na backtesting op `advice_snapshot`-data. Dit is geen juridisch of veiligheidsgarantie-advies.

## Methode

1. **Richting volgt de gemonteerde set**, niet de kalender: zomerbanden ⇒ naar winter; winterbanden ⇒ naar zomer; vierseizoenen ⇒ geen wisseladvies (alleen waarschuwingen); onbekende set ⇒ `INSUFFICIENT_DATA`.
2. De uurlijkse forecast wordt per **lokale kalenderdag** (IANA-tijdzone, DST-correct) geaggregeerd: min, max, gemiddelde.
3. Per dag wordt de **rijmoment-temperatuur** bepaald: het gemiddelde over de uren die een slot uit het rijprofiel overlappen. Heeft een dag geen slot (bijv. weekend bij pendelprofiel), dan geldt het daggemiddelde en wordt dat als reden vermeld.
4. Een dag is *koud* (rijmoment-temp < `cold_day_mean_c`) of *warm* (≥ `warm_day_mean_c`). Beslissingen gebruiken **aaneengesloten reeksen**, nooit één meting.
5. **7 °C is context**, geen beslisgrens (`cold_reference_c` wordt niet gebruikt in de regels).
6. Ontbrekende variabelen (bijv. dauwpunt, sneeuw) worden in `uncertainties` genoemd en nooit ingevuld. De uitvoer bevat geen percentages of gladheidskansen.

## Horizonnen

| Horizon | Gebruik |
|---|---|
| 0–72 u | Waarschuwingen (vorst, sneeuw, gladheid), altijd, onafhankelijk van status en hysterese |
| dag 1–7 | Concrete datum (`CHANGE_RECOMMENDED` + `recommended_date`) |
| dag 8–14 | Trend: `PREPARE_CHANGE` met `recommended_period`, nooit een exacte datum (alleen als de provider data tot daar levert) |
| daarbuiten | Geen datum |

Kan de reeks door een te korte horizon niet bevestigd worden, dan geen datum en `uncertainty.beyond_horizon`.

## Statussen

- `KEEP_CURRENT`: niets te doen. `PREPARE_CHANGE`: omslag verwacht, periode bekend. `CHANGE_RECOMMENDED`: wissel met datum. `INSUFFICIENT_DATA`: geen forecast, te oud, te weinig uren, of geen bekende set.
- `recommended_date` naar winter = dag vóór de start van de koude reeks (nooit in het verleden); naar zomer = eerste dag van de warme reeks.
- `plan_appointment_by` = datum (of begin periode) − `lead_time_days`; ligt dat in het verleden dan wordt het vandaag met reden `reason.appointment_urgent`.
- Seizoensvenster: winteradvies alleen buiten [`summer_earliest`, `winter_earliest`), zomeradvies alleen binnen dat venster. Waarschuwingen gelden altijd.

## Asymmetrie

Naar winter reageert de engine sneller (veiligheid): korte koude reeks (3 dagen) volstaat, aanhoudende vorst/sneeuw telt zwaar, en een statusverhoging is direct. Naar zomer is meer bevestiging nodig: lange warme reeks (7 dagen), niet vóór 1 maart, **geen vorst of sneeuw in de hele beschikbare horizon**, en een verhoging wordt pas na `hysteresis_confirmations` evaluaties doorgevoerd.

## Waarschuwingen (0–72 u)

- **Vorst**: temperatuur ≤ `frost_threshold_c`. **Sneeuw**: `snow_cm > 0` of neerslagtype sneeuw/natte sneeuw.
- **Gladheid**: ijzel; of (niet-sneeuw) neerslag bij ≤ `icy_precip_temp_c`; of bij vorst dauwpunt ≥ temp − `icy_dewpoint_margin_c` en (indien geleverd) vochtigheid ≥ `icy_humidity_pct`.
- Met zomerbanden gemonteerd krijgt de waarschuwing detailsleutel `….summer_tires` (extra nadruk). Een waarschuwing alleen geeft nooit automatisch `CHANGE_RECOMMENDED`.
- `FORECAST_UNAVAILABLE` / `FORECAST_STALE` bij ontbrekende of verouderde data.

## Stabiliteit (hysterese)

`status` is gestabiliseerd t.o.v. `previous`; `raw_status` is de ongedempte uitkomst, `confirm_streak` telt opeenvolgende afwijkende evaluaties. Verhoging naar winter: direct. Verhoging naar zomer en elke verlaging: pas na `hysteresis_confirmations` opeenvolgende evaluaties; tot dan blijven status en datum van de vorige staan (`reason.status_held`). Richtingswissel of onvoldoende data reset. Waarschuwingen komen altijd uit de nieuwste evaluatie.

## Drempels (`EngineConfig`, standaardwaarden)

| Parameter | Standaard | Betekenis |
|---|---|---|
| `cold_reference_c` | 7.0 | alleen context |
| `cold_day_mean_c` | 5.0 | koude dag: rijmoment-temp < |
| `cold_streak_days` | 3 | aaneengesloten koude dagen voor winteradvies |
| `warm_day_mean_c` | 10.0 | warme dag: rijmoment-temp ≥ |
| `warm_streak_days` | 7 | aaneengesloten warme dagen voor zomeradvies |
| `frost_threshold_c` | 0.0 | vorst: temp ≤ |
| `persistent_frost_days` | 3 | aaneengesloten vorstdagen = zwaar winterargument |
| `persistent_snow_days` | 2 | aaneengesloten sneeuwdagen = zwaar winterargument |
| `icy_precip_temp_c` | 1.0 | neerslag bij ≤ deze temp ⇒ gladheid |
| `icy_dewpoint_margin_c` | 1.0 | dauwpuntmarge bij vorst |
| `icy_humidity_pct` | 85 | minimale vochtigheid voor dauwpuntregel |
| `precip_threshold_mm` | 0.1 | uurneerslag die telt als neerslag |
| `summer_earliest_month_day` | 03-01 | niet eerder naar zomerbanden |
| `winter_earliest_month_day` | 10-01 | vanaf hier winteradvies |
| `short_term_hours` | 72 | waarschuwingshorizon |
| `concrete_until_day` | 7 | tot en met: concrete datum |
| `trend_until_day` | 14 | tot en met: alleen periode |
| `prepare_days_before` | 3 | lengte voorbereidingsperiode vóór omslag |
| `stale_after_hours` | 6 | ouder ⇒ `FORECAST_STALE` |
| `max_forecast_age_hours` | 36 | ouder ⇒ `INSUFFICIENT_DATA` |
| `min_hours_required` | 24 | min. toekomstige uren met temperatuur |
| `min_hours_per_day` | 8 | min. uren voor een bruikbare dag |
| `hysteresis_confirmations` | 2 | evaluaties voor statuswijziging |
