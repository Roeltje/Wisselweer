# Status

| Fase | Onderdeel | Status |
|---|---|---|
| 0 | Architectuur, logo, bouw-skill | klaar |
| 1 | Core-engine + tests | klaar |
| 2 | Weerproviders, cache, API-basis (live getest) | klaar — KNMI-veldnamen en Bright Sky/WU-licentie nog verifiëren |
| 3 | Database (incl. SQLite-weerscache), voertuigen, banden, garages, REST-API | klaar |
| 4 | Privé-webinterface + auth (incl. i18n-basis, providerkeuze, modelvergelijking) | klaar |
| 5 | Landelijk advies, publisher (lokaal + SFTP), publicatie van `advice.json` | klaar |
| 6 | Docker, Debian/Ubuntu-LXC (app), backtest, docs | klaar — native LXC-installatie (Debian 13) en SFTP-publicatie naar een aparte server in de praktijk getest; Docker nog niet getest |
| na 6 | Landenregels voor winterbanden (8 landen, `WISSELWEER_PUBLISH_COUNTRIES`), 14-daagse vooruitblik (`outlook`) in `advice.json`, interne publicatieplanner (`WISSELWEER_PUBLISH_INTERVAL_HOURS`), nieuw icoon | klaar — overige 8 landen staan op de [roadmap](../ROADMAP.md) |
| na 6 | Foto per voertuig (privé; verkleind in de browser, metadata gestript op de server, nooit gepubliceerd; bestanden in `<data_dir>/photos/`, in de back-up van `update.sh`) | klaar — alleen automatisch getest; echte telefoons (camera, HEIC, EXIF-oriëntatie) nog niet geprobeerd |

## Open punten

- Docker is in de praktijk nog niet getest.
- De adviesregels en landelijke drempels zijn ongevalideerde heuristieken, zie [advice-rules.md](advice-rules.md).
