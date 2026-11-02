# Status

| Fase | Onderdeel | Status |
|---|---|---|
| 0 | Architectuur, logo, bouw-skill | klaar |
| 1 | Core-engine + tests | klaar |
| 2 | Weerproviders, cache, API-basis (live getest) | klaar — KNMI-veldnamen en Bright Sky/WU-licentie nog verifiëren |
| 3 | Database (incl. SQLite-weerscache), voertuigen, banden, garages, REST-API | klaar |
| 4 | Privé-webinterface + auth (incl. i18n-basis, providerkeuze, modelvergelijking) | klaar |
| 5 | Landelijk advies, publisher (lokaal + SFTP), publicatie van `advice.json` | klaar |
| 6 | Docker, Debian/Ubuntu-LXC (app), backtest, docs | klaar — native LXC-installatie (Debian 13) en SFTP-publicatie naar een aparte server in de praktijk getest; Docker: image op GHCR (release-workflow met provenance), installatiescript en publisher-service; in CI gebouwd en gestart (amd64), nog niet op een echte host geprobeerd |
| na 6 | Landenregels voor winterbanden (16 landen, `WISSELWEER_PUBLISH_COUNTRIES`), 14-daagse vooruitblik (`outlook`) in `advice.json`, interne publicatieplanner (`WISSELWEER_PUBLISH_INTERVAL_HOURS`), nieuw icoon | klaar — 16 landen; onzekerheden per land in [regulations.md](regulations.md) |
| na 6 | Foto per voertuig (privé; verkleind in de browser, metadata gestript op de server, nooit gepubliceerd; bestanden in `<data_dir>/photos/`, in de back-up van `update.sh`) | klaar — alleen automatisch getest; echte telefoons (camera, HEIC, EXIF-oriëntatie) nog niet geprobeerd |
| na 6 | Interface volledig beschikbaar in nl-NL, nl-BE, en en de-DE (alle teksten vertaald, taal volgt de browser tot je zelf kiest, taalkiezer in de footer; regressietest bewaakt de sleutels) | klaar — vertalingen nog niet door moedertaalsprekers nagelezen; README en docs/ zijn alleen Nederlands |
| na 6 | Kenteken opzoeken bij RDW Open Data (merk, type, bouwjaar, openstaande terugroepacties), agenda-item (`.ics`) per voertuig, tekst per wisselmethode | klaar — RDW live getest met openbare voorbeeldkentekens; `.ics` alleen automatisch getest, nog niet in echte agenda-apps geprobeerd |
| na 6 | Huisstijl gelijk aan wisselweer.nl (nieuw logo, seizoensfoto, tabbalk op mobiel), release 0.2.0 voorbereid (CHANGELOG, `docs/releasing.md`) | klaar — tag `v0.2.0` en GHCR openbaar zetten nog te doen |

## Open punten

- Docker: de CI bouwt het image, draait het installatiescript (nieuw en update) en controleert health, UID, read-only root-fs en create-admin. De eerste release (tag `v*`: image op GHCR, arm64, attestation, GitHub Release) en SFTP-publicatie vanuit de publisher-container zijn in de praktijk nog niet geprobeerd.
- De adviesregels en landelijke drempels zijn ongevalideerde heuristieken, zie [advice-rules.md](advice-rules.md).
