# Installeren op Debian/Ubuntu (LXC of VM)

Aanbevolen: een **unprivileged LXC** met de **Debian 13 (trixie)**-template; Ubuntu 24.04 of 26.04 LTS werkt ook. 1 vCPU en 512 MB RAM zijn genoeg. De systeem-Python maakt niet uit: uv installeert Python 3.12 naast de app.

## Installatie via het script

```sh
git clone <repo-url> && cd Wisselweer
sudo ./deploy/install.sh            # of: sudo ./deploy/install.sh https://host/repo.git [ref]
```

Het script is idempotent en doet het volgende:

- installeert `python3 curl ca-certificates openssh-client sqlite3` (en `git` bij een git-URL);
- maakt systeemgebruiker `wisselweer` (nologin, home `/var/lib/wisselweer`);
- `/opt/wisselweer` (root-eigendom, leesbaar), `/var/lib/wisselweer` (0750 wisselweer), `/etc/wisselweer` (0750 root:wisselweer);
- installeert uv via de officiële standalone installer in `/usr/local/bin` (vaste versie, overschrijfbaar met `UV_VERSION`) en haalt Python 3.12 naar `/opt/wisselweer/python`;
- `uv sync --frozen --no-dev --no-editable` in `/opt/wisselweer/.venv`;
- maakt `/etc/wisselweer/wisselweer.env` (0640) alleen als het nog niet bestaat, met `DATA_DIR=/var/lib/wisselweer`, `HOST=127.0.0.1` en een gegenereerde `SECRET_KEY`;
- installeert de systemd-units en start `wisselweer`.

Het script opent geen poorten en wijzigt geen firewall. Daarna: pas het env-bestand aan (`WISSELWEER_CONTACT`), herstart en maak de beheerder aan:

```sh
sudo systemctl restart wisselweer
sudo systemd-run --pty --wait --collect -p User=wisselweer \
  -p EnvironmentFile=/etc/wisselweer/wisselweer.env \
  /opt/wisselweer/.venv/bin/wisselweer create-admin --username <naam>
```

## Handmatig

Dezelfde stappen als in `deploy/install.sh`: gebruiker en mappen aanmaken, code naar `/opt/wisselweer`, `uv sync --frozen --no-dev --no-editable` met `UV_PROJECT_ENVIRONMENT=/opt/wisselweer/.venv` en `UV_PYTHON_INSTALL_DIR=/opt/wisselweer/python`, `.env.example` naar `/etc/wisselweer/wisselweer.env`, units uit `deploy/` naar `/etc/systemd/system/`, dan `systemctl daemon-reload && systemctl enable --now wisselweer`.

## Logs, updates, back-ups

- Logs: `journalctl -u wisselweer -f` (en `-u wisselweer-publish`).
- Updaten: `git pull && sudo ./deploy/update.sh`. Dit maakt eerst een back-up in `/var/backups/wisselweer` en migreert bij het herstarten.
- Back-up (database, online en consistent): `sudo sqlite3 /var/lib/wisselweer/wisselweer.db ".backup '/var/backups/wisselweer/wisselweer-$(date +%F).db'"`. Bewaar ook `/etc/wisselweer/wisselweer.env` (bevat geheimen, houd het 0600). Bewaar back-ups versleuteld en buiten de host.

## Publiceren

Kies **of** de timer **of** de interne planner (`WISSELWEER_PUBLISH_INTERVAL_HOURS`), niet allebei.

```sh
sudo systemctl enable --now wisselweer-publish.timer   # elke 6 uur, 5 min over, met willekeurige vertraging
```

Voor SFTP draait de publicatie met `HOME=/var/lib/wisselweer`. Plaats daar de sleutel en known_hosts:

```sh
sudo install -d -m 0700 -o wisselweer -g wisselweer /var/lib/wisselweer/.ssh
sudo install -m 0600 -o wisselweer -g wisselweer deploy_key /var/lib/wisselweer/.ssh/deploy_key
ssh-keyscan -p 22 <host> | sudo -u wisselweer tee /var/lib/wisselweer/.ssh/known_hosts   # controleer de vingerafdruk!
```

Zet in het env-bestand `WISSELWEER_PUBLISH_SFTP_KEY=/var/lib/wisselweer/.ssh/deploy_key` en eventueel `..._KNOWN_HOSTS=/var/lib/wisselweer/.ssh/known_hosts`. Zie [publishing.md](publishing.md) voor de beperkte deploy-gebruiker op de webserver.

## Toegang

De service luistert alleen op `127.0.0.1:8000`. Voor toegang op afstand: een VPN (WireGuard/Tailscale) of een reverse proxy met HTTPS **en** extra authenticatie (VPN, mTLS, SSO); zet dan `WISSELWEER_COOKIE_SECURE=true`. Zet de applicatie niet zonder zulke laag op het internet.

## Niet getest

De units, het installatiescript en deze handleiding zijn geschreven zonder Debian/Ubuntu-testsysteem: alleen `bash -n` is gedraaid (geen shellcheck, geen `systemd-analyze verify`). Test eerst in een wegwerp-LXC.
