# Landelijk advies publiceren

`wisselweer publish` berekent één anoniem, landelijk wisseladvies en schrijft dat als `advice.json`. Dat bestand is de enige koppeling met de publieke site; het formaat staat in [`public-advice-contract.md`](public-advice-contract.md) (schema: `src/wisselweer/publisher/public_schema.py`, `extra="forbid"`). Er gaan nooit voertuigen, kentekens, garages, contactgegevens of eigen locaties in: het bestand wordt uitsluitend gebouwd uit berekende waarden, niet uit de database.

## Methode

1. **Richting** volgt de datum (lokale tijd, Europe/Amsterdam): 1 aug t/m 31 jan ⇒ vraag "winterbanden" (engine met zomerbanden gemonteerd); 1 feb t/m 31 jul ⇒ "zomerbanden" (winterbanden gemonteerd). Configureerbaar via `NationalConfig.winter_question_from` / `summer_question_from`.
2. **Referentielocaties** (kust, binnenland, noord, oost, zuid): De Bilt, Groningen, Den Helder, Vlissingen, Maastricht, Twente (Enschede), Arnhem. Eigen lijst via `WISSELWEER_NATIONAL_LOCATIONS` (JSON).
3. Per locatie draait dezelfde engine als voor voertuigen, met profiel "overdag" en zonder voorbereidingstijd. Een providerfout maakt van die regio `INSUFFICIENT_DATA`.
4. **Samenvoegen**:
   - minder dan de helft plus één regio met data (4 van 7) ⇒ `INSUFFICIENT_DATA`;
   - zegt minstens 75% van de regio's met data hetzelfde ⇒ die status; anders `REGIONAL_DIFFERENCES`;
   - `recommended_date` alleen als alle eensgezinde regio's dezelfde datum geven; anders `recommended_period` (vroegste tot laatste datum of periode), maar alleen als elke eensgezinde regio een datum of periode onderbouwt; anders `null`;
   - `forecast_until` is de kortste voorspellingshorizon; `stale_after` is `generated_at` + 18 uur (`WISSELWEER_PUBLIC_STALE_HOURS`).
5. Vorst- en sneeuwwaarschuwingen worden niet als landelijk advies overgenomen. Bij een lokale waarschuwing voegt de samenvatting alleen een generieke zin toe over lokale gladheid en KNMI-waarschuwingen.

**Alle drempels (75%, minimaal 4 regio's, de seizoensvensters en de engine-drempels) zijn ongevalideerde heuristieken**: niet gekalibreerd aan bandenprestaties, ongevallen of klimatologie. Het landelijk advies is indicatief en vervangt geen lokale waarschuwing.

## Lokaal publiceren

```sh
WISSELWEER_CONTACT=https://example.invalid/contact uv run wisselweer publish
```

Schrijft naar `WISSELWEER_PUBLISH_DIR` (standaard `<DATA_DIR>/public/advice.json`). Het bestand wordt eerst als `advice.json.tmp` geschreven, teruggelezen en gevalideerd en daarna met `os.replace` op zijn plaats gezet (rechten 0644). Bij een fout blijft een bestaand `advice.json` ongewijzigd en is de exitcode ongelijk aan 0. In de webinterface laat Instellingen > "Publiek advies (voorbeeld)" (`GET /api/v1/public-preview`, alleen na inloggen) de uitkomst zien zonder te publiceren.

## Uploaden via SFTP (optioneel)

Zet `WISSELWEER_PUBLISH_SFTP_HOST` (en `_USER`, `_KEY`, `_PATH`, `_PORT`, `_KNOWN_HOSTS`, zie `.env.example`). Wisselweer gebruikt het systeemcommando `sftp` (zonder shell, argumenten als lijst; host, gebruiker en paden worden gevalideerd) met `BatchMode=yes` en `StrictHostKeyChecking=yes`: de hostsleutel moet dus al in `known_hosts` staan. Het bestand gaat naar `advice.json.tmp` en wordt daarna met `rename` hernoemd; OpenSSH `sftp` gebruikt daarvoor `posix-rename` als de server dat ondersteunt (OpenSSH-servers doen dat), waardoor het vervangen atomisch is. Er geldt een time-out van 60 seconden en foutmeldingen bevatten geen sleutelpaden.

Richt op de webserver een beperkte deploy-gebruiker in:

- eigen gebruiker zonder shell (`/usr/sbin/nologin`) en alleen sleutel-authenticatie;
- in `sshd_config`: `Match User deploy` met `ChrootDirectory <publicatiemap-ouder>`, `ForceCommand internal-sftp`, `AllowTcpForwarding no`, `X11Forwarding no`;
- schrijfrechten alleen op de publicatiemap (de chroot-map zelf is eigendom van root);
- een eigen sleutelpaar dat nergens anders voor dient; de private sleutel staat alleen op de Wisselweer-host (0600), `WISSELWEER_PUBLISH_SFTP_PATH` is relatief aan de chroot.

**Foutmeldingen** (de publicatie eindigt met exitcode 255 als `sftp` faalt). Diagnose, als servicegebruiker:

```sh
runuser -u wisselweer -- sftp -v -i /var/lib/wisselweer/.ssh/deploy_key -o BatchMode=yes \
  -o UserKnownHostsFile=/var/lib/wisselweer/.ssh/known_hosts deploy@<webserver-ip>
```

| Melding | Oorzaak en oplossing |
|---|---|
| `Connection refused` | sshd draait niet op de webserver: `systemctl restart ssh` (de installatie gebruikt een restart, geen reload) |
| `Host key verification failed` | hostsleutel ontbreekt in known_hosts: `ssh-keyscan` en vingerafdruk controleren, zie [install-lxc.md](install-lxc.md) |
| `Permission denied (publickey)` | publieke sleutel in `/etc/ssh/authorized_keys/deploy` komt niet overeen met `deploy_key.pub` (volledige regel, geen vingerafdruk) |

Test een publicatie met `systemctl start wisselweer-publish.service` en `journalctl -u wisselweer-publish`: een handmatig `runuser … wisselweer publish` leest het env-bestand niet.

## Planning

Het advies hoort elke 6 uur te verversen (`stale_after` staat op 18 uur). Gebruik de systemd-timer ([install-lxc.md](install-lxc.md)), cron, of de interne planner (`WISSELWEER_PUBLISH_INTERVAL_HOURS=6`, zie [install-docker.md](install-docker.md)); niet meerdere tegelijk.
