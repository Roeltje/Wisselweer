# Adviesregels (rules_version 0.2.0)

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

## Sneeuw of ijzel op korte termijn (richting winter)

Met **zomerbanden gemonteerd** geldt voor de komende `short_term_hours` (72 u): zijn er minimaal `short_term_wintry_min_hours` (2) uren met sneeuw/natte sneeuw of ijzelneerslag, dan is de uitkomst direct `CHANGE_RECOMMENDED` met `recommended_date` = vandaag en reden `reason.short_term_wintry` (parameters `start` = eerste datum, `kind` = `snow` of `ice`; sneeuw wint als beide voorkomen). Deze regel gaat **vóór** het seizoensvenster en alle andere regels: sneeuw op zomerbanden is ook in september gevaarlijk. Het lopende uur telt mee; één los uur geldt als modelruis en triggert niet.

"IJzelneerslag" is ijzel (`FREEZING_RAIN`) of niet-sneeuw-neerslag bij ≤ `icy_precip_temp_c`. Gladheid alleen door dauwpunt/rijp (zonder neerslag) blijft een waarschuwing en geeft nooit een wisseladvies. Met winterbanden gemonteerd is de regel niet van toepassing.

## Asymmetrie

Naar winter reageert de engine sneller (veiligheid): korte koude reeks (3 dagen) volstaat, aanhoudende vorst/sneeuw telt zwaar, en een statusverhoging is direct. Naar zomer is meer bevestiging nodig: lange warme reeks (7 dagen), niet vóór 1 maart, **geen vorst of sneeuw in de hele beschikbare horizon**, en een verhoging wordt pas na `hysteresis_confirmations` evaluaties doorgevoerd.

## Waarschuwingen (0–72 u)

- **Vorst**: temperatuur ≤ `frost_threshold_c`. **Sneeuw**: `snow_cm > 0` of neerslagtype sneeuw/natte sneeuw.
- **Gladheid**: ijzel; of (niet-sneeuw) neerslag bij ≤ `icy_precip_temp_c`; of bij vorst dauwpunt ≥ temp − `icy_dewpoint_margin_c` en (indien geleverd) vochtigheid ≥ `icy_humidity_pct`.
- Met zomerbanden gemonteerd krijgt de waarschuwing detailsleutel `….summer_tires` (extra nadruk). Een waarschuwing alleen geeft nooit automatisch `CHANGE_RECOMMENDED`.
- `FORECAST_UNAVAILABLE` / `FORECAST_STALE` bij ontbrekende of verouderde data.

## Stabiliteit (hysterese)

`status` is gestabiliseerd t.o.v. `previous`; `raw_status` is de ongedempte uitkomst, `confirm_streak` telt opeenvolgende afwijkende evaluaties. Verhoging naar winter: direct. Verhoging naar zomer en elke verlaging: pas na `hysteresis_confirmations` opeenvolgende evaluaties; tot dan blijven status en datum van de vorige staan (`reason.status_held`). Richtingswissel of onvoldoende data reset. Waarschuwingen komen altijd uit de nieuwste evaluatie.

## Landelijk advies

Het landelijke advies (publisher, zie [publishing.md](publishing.md)) draait dezelfde engine op 7 referentieplaatsen, zonder voorbereidingstijd (`lead_time_days=0`), met een **landelijk rijprofiel**: werkdagen (ma–vr) 07:00–09:00 en 16:00–19:00 (ochtend- en avondspits) en za/zo 10:00–18:00. Dat volgt grofweg wanneer Nederland autorijdt volgens CBS ODiN (ochtend- en avondspits op werkdagen, drukke zaterdagmiddag); de grenzen zijn een ongevalideerde heuristiek. De vooruitblik toont per dag `temp_drive_c`: het gemiddelde over de uren in dit profiel, dezelfde rijmoment-temperatuur waarop het advies beslist.

### Demping van het landelijke advies

Zonder demping sprong het landelijke advies binnen een dag heen en weer. De publicatie bewaart daarom de vorige uitkomst in `<DATA_DIR>/national_state.json` en past twee lagen toe:

1. **Per regio**: het vorige `Advice` van de regio gaat als `previous` naar de engine, dus gelden dezelfde hysteresisregels als per voertuig (richting winter strenger: direct; lichter of richting zomer strenger: na `hysteresis_confirmations` opeenvolgende evaluaties). `regions` in `advice.json` toont de gedempte regiostatussen.
2. **Landelijke status** (na het samenvoegen), met rang `KEEP_CURRENT` < `PREPARE_CHANGE` < `CHANGE_RECOMMENDED`:
   - `INSUFFICIENT_DATA` (nieuw of vorig): altijd direct.
   - Seizoen `winter` en nieuwe status hoger dan de vastgehouden status: direct.
   - Elke andere wijziging (lager, van/naar `REGIONAL_DIFFERENCES`, of hoger in seizoen `summer`): pas als dezelfde ruwe landelijke status `hysteresis_confirmations` berekeningen op rij voorkomt.
   - Tijdens vasthouden blijven status, `status_label`, samenvatting, `recommended_date` en `recommended_period` van de vorige berekening staan (de waarschuwingsnotitie volgt de nieuwe berekening).

Omdat beide lagen dempen, kan een landelijke daling in totaal drie publicaties duren (twee voor de regio's, daarna de landelijke bevestiging). Dat is bewust: liever te lang "Tijd om te wisselen" dan heen-en-weer. De staat wordt genegeerd als het bestand ontbreekt of onleesbaar is, ouder is dan 48 uur, of van een ander seizoen is. Alleen `wisselweer publish` schrijft de staat; `GET /api/v1/public-preview` leest hem alleen.

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
| `short_term_wintry_min_hours` | 2 | uren sneeuw/ijzelneerslag binnen `short_term_hours` voor direct wisseladvies met zomerbanden |
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
