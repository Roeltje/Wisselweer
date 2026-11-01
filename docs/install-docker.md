# Installeren met Docker

Het image staat op GitHub Container Registry: `ghcr.io/roeltje/wisselweer` (tags `<versie>`, `<major>.<minor>` en `latest`, voor `linux/amd64` en `linux/arm64`).

## Vereisten

- Docker Engine met Compose v2 (`docker compose`) en een gebruiker die Docker mag gebruiken (root is niet nodig).
- `curl` (voor het installatiescript).
- Een host waarop je de poort niet naar het internet opent (zie [Toegang op afstand](#toegang-op-afstand)).

## Snelle installatie

```sh
curl -fsSLO https://github.com/Roeltje/Wisselweer/releases/latest/download/docker-install.sh
bash docker-install.sh            # installeert in ./wisselweer
```

Kies een andere map met `bash docker-install.sh /pad/naar/map` en een vaste versie met `--version v0.1.0`. Het script:

- controleert of `docker`, `docker compose` (v2) en toegang tot de daemon er zijn;
- haalt `compose.yaml` en `.env.example` van de release (alleen https) en verplaatst ze pas als alles gelukt is;
- maakt `.env` aan als die nog niet bestaat: met een gegenereerde `WISSELWEER_SECRET_KEY`, rechten 600 en het contactgegeven dat je invult (of `WISSELWEER_CONTACT=… bash docker-install.sh`; dat is een URL of e-mailadres voor de User-Agent richting MET Norway). Een bestaand `.env` wordt nooit aangepast;
- haalt het image op, start Wisselweer en wacht tot de container gezond is.

Maak daarna de beheerder aan, in de installatiemap (het wachtwoord wordt gevraagd; minimaal 10 tekens):

```sh
cd wisselweer
docker compose exec wisselweer wisselweer create-admin --username <naam>
```

Open `http://127.0.0.1:8000`. Zet in `.env` `WISSELWEER_COOKIE_SECURE=true` zodra je achter HTTPS draait. `compose.yaml` forceert zelf `WISSELWEER_HOST=0.0.0.0` en `WISSELWEER_DATA_DIR=/data` binnen de container; die twee regels in `.env` worden genegeerd. `.env` komt niet in de image (`.dockerignore`).

De container draait als niet-root gebruiker `wisselweer` (UID 10001) met een read-only root-bestandssysteem, `no-new-privileges` en zonder Linux-capabilities. Alleen het volume `wisselweer-data` (`/data`) is schrijfbaar. De poort is op de host alleen aan localhost gebonden.

## Handmatig met Compose

Wat het script doet, kan ook met de hand. Download `compose.yaml` en `env.example` van de [release](https://github.com/Roeltje/Wisselweer/releases) in een lege map:

```sh
cp env.example .env
chmod 600 .env
# Vul WISSELWEER_CONTACT in en een geheime sleutel (minimaal 32 tekens):
#   python3 -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose pull
docker compose up -d
```

`compose.yaml` van een release wijst naar het image van diezelfde versie. `IMAGE_TAG` in `.env` (een Compose-variabele, geen `WISSELWEER_`-instelling; de app negeert hem) kiest een andere tag, bijvoorbeeld `IMAGE_TAG=latest` om altijd de nieuwste te volgen of `IMAGE_TAG=0.1` voor alleen patchreleases.

## Zelf bouwen

Vanaf de broncode (een kloon van de repository), zonder image van GHCR:

```sh
cp .env.example .env              # en invullen, zoals hierboven
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

`compose.build.yaml` zet `build: .` en het lokale image `wisselweer:local`. Gebruik altijd `--build`; ook de publisher gebruikt dat image. Voor de publisher voeg je `--profile publish` toe.

## Publiceren

De service `publisher` publiceert het landelijke advies periodiek (`wisselweer publish --every-hours 6`; eerste run een minuut na het starten, netjes stoppen op `docker compose stop`). Hij hoort bij het profiel `publish` en draait dus alleen als je erom vraagt. Dit is het Docker-equivalent van `wisselweer-publish.timer` onder systemd: alleen de publisher-container kan de SFTP-sleutel lezen, de webapp niet. Een gecompromitteerde webapp kan de sleutel dus niet stelen.

1. Maak naast `compose.yaml` een map `secrets/` met de private sleutel van de deploy-gebruiker (`deploy_key`) en `known_hosts` (met de hostsleutel van de doelserver). De sleutel moet leesbaar zijn voor UID 10001 en voor niemand anders: `sudo chown 10001 secrets/deploy_key && chmod 600 secrets/deploy_key`. Bestaat `secrets/` niet, dan weigert Compose de publisher te starten.
2. Zet in `.env`:
   ```
   WISSELWEER_PUBLISH_SFTP_HOST=sftp.example.invalid
   WISSELWEER_PUBLISH_SFTP_USER=deploy
   WISSELWEER_PUBLISH_SFTP_KEY=/run/secrets/deploy_key
   WISSELWEER_PUBLISH_SFTP_KNOWN_HOSTS=/run/secrets/known_hosts
   WISSELWEER_PUBLISH_INTERVAL_HOURS=0
   ```
   `WISSELWEER_PUBLISH_INTERVAL_HOURS` moet in de webapp op `0` blijven (de standaard): anders publiceert de webapp ook zelf, zonder toegang tot de sleutel, en mislukt dat. Het interval van de publisher stel je in met `PUBLISH_EVERY_HOURS` in `.env` (standaard 6).
3. Start: `docker compose --profile publish up -d`. Wil je dat de publisher altijd meedraait (ook bij `docker compose up -d` en bij updates), zet dan `COMPOSE_PROFILES=publish` in `.env`.
4. Test: `docker compose --profile publish run --rm --no-deps publisher wisselweer publish` en bekijk `docker compose --profile publish logs publisher`.

Zonder SFTP (alleen lokaal schrijven naar `/data/public`) heb je de publisher niet nodig: zet dan `WISSELWEER_PUBLISH_INTERVAL_HOURS=6` in `.env` en herstart. Gebruik nooit twee manieren tegelijk. Zie [publishing.md](publishing.md).

## Updaten

Draai het installatiescript opnieuw (in dezelfde map, of geef de map op):

```sh
bash docker-install.sh            # nieuwste release; of: --version v0.2.0
```

Bij een bestaande installatie maakt het script eerst een back-up in `backups/` (database, voertuigfoto's en de vorige `compose.yaml`; rechten 700/600), haalt dan de nieuwe `compose.yaml` en het image op en start opnieuw. Je `.env` en gegevens blijven ongewijzigd; migraties draaien bij het opstarten. Draait de publisher, dan wordt die meegenomen.

Zonder script: haal een nieuwe `compose.yaml` van de release (of zet `IMAGE_TAG=<nieuwe versie>` in `.env`) en draai `docker compose pull && docker compose up -d` (met `--profile publish` als je de publisher gebruikt). Maak vooraf een back-up.

## Back-up en herstel

Het script maakt bij elke update een back-up in `backups/`. Handmatig, consistente kopie van de SQLite-database (container mag blijven draaien):

```sh
docker compose exec wisselweer python -c "import sqlite3,sys; s=sqlite3.connect('/data/wisselweer.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close()"
docker compose cp wisselweer:/data/backup.db ./wisselweer-$(date +%F).db
docker compose exec wisselweer rm /data/backup.db
```

Voertuigfoto's staan als bestanden in `/data/photos/` (dus in hetzelfde volume) en horen ook in de back-up. De tar-uitvoer gaat via stdout naar de host (`docker compose cp` ziet de tmpfs `/tmp` niet):

```sh
docker compose exec -T wisselweer tar -C /data -czf - photos > wisselweer-$(date +%F)-photos.tar.gz
```

Bewaar de back-up en je `.env` buiten de host en versleuteld: ze bevatten persoonsgegevens en geheimen.

Herstellen (in de installatiemap; vervang `<stempel>` door die van de back-up). De bestanden gaan via stdin het volume in, zodat ze eigendom van UID 10001 worden:

```sh
docker compose stop
docker compose run --rm --no-deps -T wisselweer sh -c 'rm -f /data/wisselweer.db-wal /data/wisselweer.db-shm && cat > /data/wisselweer.db' < backups/wisselweer-<stempel>.db
docker compose run --rm --no-deps -T wisselweer tar -C /data -xzf - < backups/wisselweer-<stempel>-photos.tar.gz
docker compose up -d
```

Sla de tweede regel over als je geen foto's hebt. Het volume heet `wisselweer_wisselweer-data` (`docker volume ls`).

## Het image controleren

Elk release-image heeft een herkomstverklaring (SLSA build provenance, ondertekend door GitHub Actions) en een SBOM. Controleer dat het image echt uit deze repository en workflow komt:

```sh
gh attestation verify oci://ghcr.io/roeltje/wisselweer:<versie> --owner Roeltje
```

Gebruik de versie zonder `v` (bijvoorbeeld `0.1.0`).

## Toegang op afstand

Open de poort niet naar het internet en bind niet aan `0.0.0.0` op de host. Gebruik een VPN (WireGuard, Tailscale) en benader de host via het VPN-adres, bijvoorbeeld met `tailscale serve`, of zet een reverse proxy met HTTPS en eigen extra authenticatie (VPN, mTLS of SSO) ervoor.

## Wat is getest

Het image wordt in CI bij elke wijziging gebouwd en gestart (amd64); arm64 wordt alleen bij een release gebouwd. De CI draait daarbij het installatiescript (nieuwe installatie en update), controleert health, UID, read-only root-bestandssysteem, `.env`-rechten, het aanmaken van een beheerder, de back-up en het netjes stoppen van de publisher. SFTP-publicatie vanuit de publisher-container is nog niet in CI getest (alleen het starten en stoppen).
