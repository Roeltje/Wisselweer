# Installeren op Debian/Ubuntu (LXC of VM)

Aanbevolen: een **unprivileged LXC** met de **Debian 13 (trixie)**-template; Ubuntu 24.04 of 26.04 LTS werkt ook. 1 vCPU en 512 MB RAM zijn genoeg. De systeem-Python maakt niet uit: uv installeert Python 3.12 naast de app.

## Installatie via het script

```sh
git clone <repo-url> && cd Wisselweer
./deploy/install.sh            # als root; of: ./deploy/install.sh https://host/repo.git [ref]
```

Draai alles als root. In een Debian-LXC is `sudo` meestal niet geïnstalleerd; op een systeem met sudo zet je `sudo` ervoor. Commando's als servicegebruiker draai je met `runuser -u wisselweer -- …` (in plaats van `sudo -u wisselweer …`).

Het script is idempotent en doet het volgende:

- installeert `python3 curl ca-certificates openssh-client sqlite3` (en `git` bij een git-URL);
- maakt systeemgebruiker `wisselweer` (nologin, home `/var/lib/wisselweer`);
- `/opt/wisselweer` (root-eigendom, leesbaar), `/var/lib/wisselweer` (0750 wisselweer), `/etc/wisselweer` (0750 root:wisselweer);
- maakt `/var/lib/wisselweer/.ssh` (0700, eigendom wisselweer) voor de SFTP-sleutel en known_hosts;
- installeert uv via de officiële standalone installer in `/usr/local/bin` (vaste versie, overschrijfbaar met `UV_VERSION`; het script roept uv aan via dat vaste pad, ook als `/usr/local/bin` niet in je PATH staat) en haalt Python 3.12 naar `/opt/wisselweer/python`;
- `uv sync --frozen --no-dev --no-editable` in `/opt/wisselweer/.venv`;
- maakt `/etc/wisselweer/wisselweer.env` (0640) alleen als het nog niet bestaat, met `DATA_DIR=/var/lib/wisselweer`, `HOST=127.0.0.1` en een gegenereerde `SECRET_KEY`;
- installeert de systemd-units en start `wisselweer`.

Is het script halverwege afgebroken en bestaat `/etc/wisselweer/wisselweer.env` niet, draai dan gewoon `install.sh` opnieuw: het is idempotent en maakt het env-bestand dan aan, met een gegenereerde secret key. Maak het env-bestand niet met de hand.

Het script opent geen poorten en wijzigt geen firewall. Daarna: pas het env-bestand aan (`WISSELWEER_CONTACT`), herstart en maak de beheerder aan (wachtwoord minimaal 10 tekens):

```sh
systemctl restart wisselweer
systemd-run --pty --wait --collect -p User=wisselweer \
  -p EnvironmentFile=/etc/wisselweer/wisselweer.env \
  /opt/wisselweer/.venv/bin/wisselweer create-admin --username <naam>
```

Een handmatig `runuser -u wisselweer -- wisselweer …` laadt `/etc/wisselweer/wisselweer.env` **niet**; gebruik daarom de `systemd-run`-vorm hierboven (met `-p EnvironmentFile=`) voor commando's die de configuratie nodig hebben.

## Handmatig

Dezelfde stappen als in `deploy/install.sh`: gebruiker en mappen aanmaken, code naar `/opt/wisselweer`, `uv sync --frozen --no-dev --no-editable` met `UV_PROJECT_ENVIRONMENT=/opt/wisselweer/.venv` en `UV_PYTHON_INSTALL_DIR=/opt/wisselweer/python`, `.env.example` naar `/etc/wisselweer/wisselweer.env`, units uit `deploy/` naar `/etc/systemd/system/`, dan `systemctl daemon-reload && systemctl enable --now wisselweer`.

## Logs, updates, back-ups

- Logs: `journalctl -u wisselweer -f` (en `-u wisselweer-publish`).
- Updaten: `git pull && ./deploy/update.sh`. Dit maakt eerst een back-up in `/var/backups/wisselweer` en migreert bij het herstarten.
- Back-up (database, online en consistent): `sqlite3 /var/lib/wisselweer/wisselweer.db ".backup '/var/backups/wisselweer/wisselweer-$(date +%F).db'"`. Bewaar ook `/etc/wisselweer/wisselweer.env` (bevat geheimen, houd het 0600). Bewaar back-ups versleuteld en buiten de host.

## Publiceren

Volgorde voor publicatie via SFTP naar een webserver (elke statische host met een gechroote SFTP-gebruiker; zie [publishing.md](publishing.md)). De webserver zelf valt buiten deze repo:

1. **Sleutel maken** op de app-LXC, als servicegebruiker (de map `.ssh` bestaat al na `install.sh`):
   ```sh
   runuser -u wisselweer -- ssh-keygen -t ed25519 -N '' -C wisselweer-publish -f /var/lib/wisselweer/.ssh/deploy_wisselweer_web
   cat /var/lib/wisselweer/.ssh/deploy_wisselweer_web.pub
   ```
2. **Publieke sleutel op de webserver**: zet de volledige regel `ssh-ed25519 AAAA… wisselweer-publish` (dus niet de SHA256-vingerafdruk) in de `authorized_keys` van de deploy-gebruiker, bijvoorbeeld `/etc/ssh/authorized_keys/deploy`.
3. **Hostsleutel vastleggen** op de app-LXC en de vingerafdruk op beide kanten vergelijken:
   ```sh
   ssh-keyscan -t ed25519 -p 22 <webserver-ip> | runuser -u wisselweer -- tee /var/lib/wisselweer/.ssh/known_hosts
   runuser -u wisselweer -- ssh-keygen -lf /var/lib/wisselweer/.ssh/known_hosts   # app-LXC
   ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub                                # webserver
   ```
4. **Env instellen** in `/etc/wisselweer/wisselweer.env`: `WISSELWEER_PUBLISH_SFTP_HOST=<webserver-ip>`, `..._USER=deploy`, `..._KEY=/var/lib/wisselweer/.ssh/deploy_wisselweer_web`, `..._KNOWN_HOSTS=/var/lib/wisselweer/.ssh/known_hosts` en `..._PATH=/site` (relatief aan de chroot van de deploy-gebruiker).
5. **Test-publicatie** via systemd, zodat het env-bestand wordt geladen:
   ```sh
   systemctl start wisselweer-publish.service
   journalctl -u wisselweer-publish -n 30
   ```
6. **Plannen**: kies **of** de timer **of** de interne planner (`WISSELWEER_PUBLISH_INTERVAL_HOURS`), niet allebei.
   ```sh
   systemctl enable --now wisselweer-publish.timer   # elke 6 uur, 5 min over, met willekeurige vertraging
   ```

Zie [publishing.md](publishing.md) voor de beperkte deploy-gebruiker op de webserver en het oplossen van SFTP-fouten.

## Toegang

De service luistert standaard alleen op `127.0.0.1:8000`. Voor toegang op afstand: een VPN (WireGuard/Tailscale) of een reverse proxy met HTTPS **en** extra authenticatie (VPN, mTLS, SSO). Zet de applicatie niet zonder zulke laag op het internet.

**Reverse proxy op een andere host** (bijv. Nginx Proxy Manager op `192.0.2.10`): zet in het env-bestand `WISSELWEER_HOST=0.0.0.0` en, alleen achter https, `WISSELWEER_COOKIE_SECURE=true`. Beperk poort 8000 tot het IP van de proxy, bijvoorbeeld met een kleine nftables-regel:

```sh
nft add table inet ww
nft add chain inet ww input '{ type filter hook input priority 0; }'
nft add rule inet ww input tcp dport 8000 ip saddr != 192.0.2.10 drop
```

Zet dit voor blijvend gebruik in `/etc/nftables.conf`. Houd de app bij voorkeur alleen intern bereikbaar: interne DNS-naam (bijv. `app.example.org`), geen publiek DNS-record.

## Getest

De native installatie op Debian 13 (unprivileged LXC) is in de praktijk getest, samen met een aparte statische webserver op een tweede LXC. De units en het script zijn niet door shellcheck of `systemd-analyze verify` gehaald. Docker is nog niet getest, zie [install-docker.md](install-docker.md).
