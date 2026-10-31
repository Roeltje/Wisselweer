# Installeren met Docker

## Vereisten

- Docker Engine met Compose v2 (`docker compose`).
- Een host waarop je de poort niet naar het internet opent (zie [Toegang op afstand](#toegang-op-afstand)).

## Stappen

1. Maak je configuratie: `cp .env.example .env` en vul minstens `WISSELWEER_CONTACT` en `WISSELWEER_SECRET_KEY` in (`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Zet `WISSELWEER_COOKIE_SECURE=true` zodra je achter HTTPS draait. `compose.yaml` forceert zelf `WISSELWEER_HOST=0.0.0.0` en `WISSELWEER_DATA_DIR=/data` binnen de container; die twee regels in `.env` worden genegeerd. `.env` komt niet in de image (`.dockerignore`).
2. Bouwen en starten: `docker compose up -d --build`. Migraties draaien automatisch bij het opstarten.
3. Beheerder aanmaken: `docker compose exec wisselweer wisselweer create-admin --username <naam>` (het wachtwoord wordt gevraagd).
4. Open `http://127.0.0.1:8000`. De poort is op de host alleen aan localhost gebonden.

De container draait als niet-root gebruiker `wisselweer` (UID 10001) met een read-only root-bestandssysteem, `no-new-privileges` en zonder Linux-capabilities. Alleen het volume `wisselweer-data` (`/data`) is schrijfbaar.

## Publiceren

- Intern: zet `WISSELWEER_PUBLISH_INTERVAL_HOURS=6` in `.env` en herstart (`docker compose up -d`). De eerste run volgt een minuut na het starten.
- Of handmatig / via een cron op de host: `docker compose exec wisselweer wisselweer publish`.

Gebruik niet beide. Voor SFTP-upload: mount de sleutel en known_hosts (zie de uitgecommentarieerde regels in `compose.yaml`; de sleutel moet leesbaar zijn voor UID 10001, bijvoorbeeld `chown 10001 secrets/deploy_key; chmod 600`) en zet `WISSELWEER_PUBLISH_SFTP_*` in `.env`. Zie [publishing.md](publishing.md).

## Updaten

```sh
git pull
docker compose up -d --build
```

Maak vooraf een back-up. De database wordt bij het opstarten gemigreerd.

## Back-up van het volume

Consistente kopie van de SQLite-database (container mag blijven draaien):

```sh
docker compose exec wisselweer python -c "import sqlite3,sys; s=sqlite3.connect('/data/wisselweer.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close()"
docker compose cp wisselweer:/data/backup.db ./wisselweer-$(date +%F).db
docker compose exec wisselweer rm /data/backup.db
```

Bewaar de back-up en je `.env` buiten de host en versleuteld: ze bevatten persoonsgegevens en geheimen. Herstellen: stop de container, kopieer het bestand terug naar `/data/wisselweer.db` (bijv. met een tijdelijke container die het volume mount) en start opnieuw.

## Toegang op afstand

Open de poort niet naar het internet en bind niet aan `0.0.0.0` op de host. Gebruik een VPN (WireGuard, Tailscale) en benader de host via het VPN-adres, bijvoorbeeld met `tailscale serve`, of zet een reverse proxy met HTTPS en eigen extra authenticatie (VPN, mTLS of SSO) ervoor.

## Niet getest

Dockerfile en compose.yaml (anders dan de LXC-installatie, die wel getest is) zijn geschreven op een machine zonder Docker en daar niet gebouwd of gedraaid. Controleer bij de eerste build vooral de uv-image-tag en de healthcheck (`docker compose ps`).
