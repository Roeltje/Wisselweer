#!/usr/bin/env bash
# Wisselweer: installeren of bijwerken met Docker (Compose v2). Idempotent; draai als gewone
# gebruiker met toegang tot Docker (root is niet nodig):
#   curl -fsSLO https://github.com/Roeltje/Wisselweer/releases/latest/download/docker-install.sh
#   bash docker-install.sh [--version vX.Y.Z] [map]        # standaardmap: ./wisselweer
#
# Keuzes:
# - Haalt compose.yaml en .env.example van de GitHub Release (alleen https, TLS 1.2+) naar een
#   tijdelijke map en verplaatst ze pas als alles gelukt is. compose.yaml van een release
#   verwijst naar het image van diezelfde versie op ghcr.io.
# - Maakt .env alleen aan als hij nog niet bestaat (met een gegenereerde geheime sleutel, rechten
#   600) en past een bestaand .env nooit aan.
# - Draait er al een installatie in de map, dan komt eerst een back-up in <map>/backups/.
# - Opent geen poorten: de webapp is alleen op 127.0.0.1:8000 bereikbaar. Maakt geen beheerder aan.
# Alleen voor testen (CI): WISSELWEER_ASSETS_DIR (lokale map met de bestanden, niets downloaden),
# IMAGE_TAG (image-tag voor Compose), WISSELWEER_SKIP_PULL=1 (geen `docker compose pull`, voor een
# lokaal gebouwd image) en WISSELWEER_HEALTH_TIMEOUT (seconden wachten, standaard 120).
set -euo pipefail

readonly REPO="Roeltje/Wisselweer"
readonly RELEASES_URL="https://github.com/$REPO/releases"
HEALTH_TIMEOUT="${WISSELWEER_HEALTH_TIMEOUT:-120}"

# Alles wat we aanmaken (map, .env, back-ups) is alleen voor de eigenaar leesbaar.
umask 077

info() { echo "==> $*"; }
warn() { echo "Let op: $*" >&2; }
die() { echo "Fout: $*" >&2; exit 1; }

usage() {
  cat <<'MSG'
Gebruik: bash docker-install.sh [--version vX.Y.Z] [map]

  map        installatiemap (standaard ./wisselweer)
  --version  release om te installeren, bv. v0.1.0 (standaard: de nieuwste)

Bij een eerste installatie is WISSELWEER_CONTACT nodig (URL of e-mailadres voor de User-Agent
richting MET Norway): je krijgt een vraag, of zet de omgevingsvariabele
  WISSELWEER_CONTACT=https://example.invalid/contact bash docker-install.sh
MSG
}

VERSION="latest"
DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --version)
      [[ $# -ge 2 ]] || die "--version vraagt een waarde, bv. --version v0.1.0"
      VERSION="$2"; shift 2 ;;
    --version=*) VERSION="${1#--version=}"; shift ;;
    -*) die "Onbekende optie: $1 (zie --help)" ;;
    *)
      [[ -z "$DIR" ]] || die "Geef maximaal een map op."
      DIR="$1"; shift ;;
  esac
done
DIR="${DIR:-./wisselweer}"
if [[ "$VERSION" != "latest" && ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  die "Ongeldige versie '$VERSION': gebruik de vorm v1.2.3 (of laat --version weg voor de nieuwste)."
fi
if [[ ! "$HEALTH_TIMEOUT" =~ ^[0-9]+$ ]]; then
  die "WISSELWEER_HEALTH_TIMEOUT moet een aantal seconden zijn."
fi

# --- Controles ---------------------------------------------------------------------------------
if [[ $EUID -eq 0 ]]; then
  warn "je draait dit als root. Dat is niet nodig; een gewone gebruiker met Docker-toegang volstaat."
fi
command -v docker >/dev/null 2>&1 \
  || die "docker niet gevonden. Installeer Docker Engine: https://docs.docker.com/engine/install/"
COMPOSE_VERSION="$(docker compose version --short 2>/dev/null)" \
  || die "'docker compose' (Compose v2) ontbreekt. Installeer de Compose-plugin: https://docs.docker.com/compose/install/"
COMPOSE_VERSION="${COMPOSE_VERSION#v}"
COMPOSE_MAJOR="${COMPOSE_VERSION%%.*}"
if [[ ! "$COMPOSE_MAJOR" =~ ^[0-9]+$ ]] || [[ "$COMPOSE_MAJOR" -lt 2 ]]; then
  die "Docker Compose v2 is nodig (gevonden: '$COMPOSE_VERSION')."
fi
docker info >/dev/null 2>&1 \
  || die "Geen toegang tot de Docker-daemon. Draait Docker, en mag jouw gebruiker erbij (groep 'docker')?"
if [[ -z "${WISSELWEER_ASSETS_DIR:-}" ]]; then
  command -v curl >/dev/null 2>&1 || die "curl niet gevonden. Installeer curl en probeer opnieuw."
fi

# --- Map en tijdelijke werkruimte --------------------------------------------------------------
mkdir -p "$DIR"
DIR="$(cd "$DIR" && pwd)"
# In dezelfde map, zodat het verplaatsen aan het eind een rename is en .env nooit elders belandt.
TMP="$(mktemp -d "$DIR/.installer.XXXXXX")"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

EXISTING=0
if [[ -f "$DIR/compose.yaml" ]]; then EXISTING=1; fi
if [[ $EXISTING -eq 1 ]]; then
  info "Bestaande installatie gevonden in $DIR: dit wordt een update."
else
  info "Nieuwe installatie in $DIR"
fi

# --- Bestanden ophalen -------------------------------------------------------------------------
if [[ "$VERSION" == "latest" ]]; then
  BASE_URL="$RELEASES_URL/latest/download"
else
  BASE_URL="$RELEASES_URL/download/$VERSION"
fi

# fetch <assetnaam> <doelnaam in $TMP>
fetch() {
  local asset="$1" dest="$2"
  if [[ -n "${WISSELWEER_ASSETS_DIR:-}" ]]; then
    if [[ -f "$WISSELWEER_ASSETS_DIR/$asset" ]]; then
      cp "$WISSELWEER_ASSETS_DIR/$asset" "$TMP/$dest"
    elif [[ "$asset" == "env.example" && -f "$WISSELWEER_ASSETS_DIR/.env.example" ]]; then
      cp "$WISSELWEER_ASSETS_DIR/.env.example" "$TMP/$dest"
    else
      die "Ontbreekt in WISSELWEER_ASSETS_DIR: $asset"
    fi
  else
    curl --proto '=https' --tlsv1.2 -fsSL -o "$TMP/$dest" "$BASE_URL/$asset" \
      || die "Downloaden mislukt: $BASE_URL/$asset (bestaat die versie?)"
  fi
}

if [[ -n "${WISSELWEER_ASSETS_DIR:-}" ]]; then
  info "Bestanden uit $WISSELWEER_ASSETS_DIR (geen download)"
else
  info "Bestanden downloaden van $BASE_URL"
fi
fetch compose.yaml compose.yaml
# GitHub hernoemt release-bestanden met een punt vooraan; vandaar `env.example` als assetnaam.
fetch env.example env.example
grep -q '^services:' "$TMP/compose.yaml" || die "compose.yaml lijkt ongeldig (geen 'services:')."
grep -q '^WISSELWEER_SECRET_KEY=' "$TMP/env.example" && grep -q '^WISSELWEER_CONTACT=' "$TMP/env.example" \
  || die ".env.example lijkt ongeldig (WISSELWEER_SECRET_KEY of WISSELWEER_CONTACT ontbreekt)."

# --- .env voorbereiden (alleen als hij nog niet bestaat) ---------------------------------------
NEW_ENV=0
if [[ -e "$DIR/.env" ]]; then
  info ".env bestaat al; niet aangepast"
else
  NEW_ENV=1
  CONTACT="${WISSELWEER_CONTACT:-}"
  if [[ -z "$CONTACT" ]]; then
    if [[ -t 0 ]]; then
      echo "Wisselweer stuurt een contactgegeven mee naar MET Norway (verplichte User-Agent)."
      read -r -p "Contactgegeven (URL of e-mailadres): " CONTACT
    else
      die "WISSELWEER_CONTACT is verplicht bij een eerste installatie (geen terminal om het te vragen). Voorbeeld: WISSELWEER_CONTACT=https://example.invalid/contact bash docker-install.sh"
    fi
  fi
  [[ -n "$CONTACT" ]] || die "Een contactgegeven is verplicht."
  CONTACT_RE='^[A-Za-z0-9@._:/?=&+~%,-]+$'
  [[ "$CONTACT" =~ $CONTACT_RE ]] \
    || die "Het contactgegeven bevat spaties of tekens die in een .env-bestand problemen geven. Gebruik een URL of e-mailadres zonder spaties, aanhalingstekens, \$, # of \\."
  # 48 willekeurige bytes -> 64 URL-veilige tekens (>= 32 vereist door de app).
  SECRET="$(head -c 48 /dev/urandom | base64 | tr -d '\n=' | tr '+/' '-_')"
  [[ ${#SECRET} -ge 48 ]] || die "Geheime sleutel genereren mislukt."
  # ENVIRON i.p.v. -v: awk verwerkt geen backslashes in de waarden.
  SECRET="$SECRET" CONTACT="$CONTACT" awk '
    /^WISSELWEER_SECRET_KEY=/ { print "WISSELWEER_SECRET_KEY=" ENVIRON["SECRET"]; next }
    /^WISSELWEER_CONTACT=/ { print "WISSELWEER_CONTACT=" ENVIRON["CONTACT"]; next }
    { print }
  ' "$TMP/env.example" > "$TMP/env.new"
  chmod 600 "$TMP/env.new"
  grep -q '^WISSELWEER_SECRET_KEY=.\{48,\}$' "$TMP/env.new" || die "Aanmaken van .env mislukt."
  unset SECRET
fi

# --- Back-up (alleen bij een update) -----------------------------------------------------------
# De SQLite-back-up loopt via python in een tijdelijke container met hetzelfde volume en stroomt
# naar stdout: er blijft niets achter in het volume. Veilig terwijl de webapp draait.
BACKUP_PY='
import os, shutil, sqlite3, sys, tempfile
db = "/data/wisselweer.db"
if not os.path.exists(db):
    sys.exit(3)
with tempfile.TemporaryDirectory() as tmp:
    out = os.path.join(tmp, "backup.db")
    src = sqlite3.connect(db)
    dst = sqlite3.connect(out)
    src.backup(dst)
    dst.close()
    src.close()
    with open(out, "rb") as f:
        shutil.copyfileobj(f, sys.stdout.buffer)
    sys.stdout.buffer.flush()
'

backup() {
  local stamp rc=0 file
  stamp="$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$DIR/backups"
  chmod 700 "$DIR/backups"
  info "Back-up maken in $DIR/backups"
  file="$DIR/backups/wisselweer-$stamp.db"
  docker compose run --rm --no-deps -T wisselweer python -c "$BACKUP_PY" > "$file" || rc=$?
  case "$rc" in
    0) chmod 600 "$file"; echo "Database-back-up: $file" ;;
    3) rm -f "$file"; echo "Nog geen database aanwezig; geen database-back-up nodig." ;;
    *) rm -f "$file"; die "Back-up van de database mislukt (exitcode $rc). Update afgebroken; er is niets gewijzigd." ;;
  esac
  # Voertuigfoto's staan als bestanden naast de database en horen bij de back-up.
  if docker compose run --rm --no-deps -T wisselweer test -d /data/photos; then
    file="$DIR/backups/wisselweer-$stamp-photos.tar.gz"
    if docker compose run --rm --no-deps -T wisselweer tar -C /data -czf - photos > "$file"; then
      chmod 600 "$file"
      echo "Foto-back-up: $file"
    else
      rm -f "$file"
      die "Foto-back-up mislukt. Update afgebroken; er is niets gewijzigd."
    fi
  fi
  if ! cmp -s "$DIR/compose.yaml" "$TMP/compose.yaml"; then
    cp "$DIR/compose.yaml" "$DIR/backups/compose-$stamp.yaml"
    echo "Vorige compose.yaml bewaard: $DIR/backups/compose-$stamp.yaml"
  fi
}

cd "$DIR"
if [[ $EXISTING -eq 1 ]]; then
  # Een draaiende publisher (profiel `publish`) hoort ook bij de update.
  if [[ -n "$(docker compose --profile publish ps -q publisher 2>/dev/null || true)" ]]; then
    export COMPOSE_PROFILES="${COMPOSE_PROFILES:+$COMPOSE_PROFILES,}publish"
    info "Publisher-container gevonden; die wordt ook bijgewerkt."
  fi
  # Zonder .env is er geen werkende installatie om een back-up van te maken.
  if [[ $NEW_ENV -eq 0 ]]; then backup; fi
fi

# --- Bestanden op hun plek zetten (pas nu alles gelukt is) ------------------------------------
if [[ $NEW_ENV -eq 1 ]]; then mv "$TMP/env.new" "$DIR/.env"; fi
mv "$TMP/env.example" "$DIR/.env.example"
mv "$TMP/compose.yaml" "$DIR/compose.yaml"

# --- Image ophalen en starten ------------------------------------------------------------------
if [[ -n "${IMAGE_TAG:-}" ]]; then info "Image-tag: $IMAGE_TAG"; fi
if [[ -n "${WISSELWEER_SKIP_PULL:-}" ]]; then
  info "Image ophalen overgeslagen (WISSELWEER_SKIP_PULL)"
else
  info "Image ophalen"
  docker compose pull
fi
info "Starten"
docker compose up -d

wait_healthy() {
  local id state waited=0
  id="$(docker compose ps -q wisselweer)"
  [[ -n "$id" ]] || die "De container 'wisselweer' is niet gestart; zie: docker compose logs"
  info "Wachten tot Wisselweer gezond is (maximaal ${HEALTH_TIMEOUT}s)"
  while :; do
    state="$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id" 2>/dev/null || true)"
    case "$state" in
      "running healthy") return 0 ;;
      exited* | dead*) break ;;
    esac
    if [[ $waited -ge $HEALTH_TIMEOUT ]]; then break; fi
    sleep 2
    waited=$((waited + 2))
  done
  docker compose logs --tail 40 wisselweer >&2 || true
  die "Wisselweer werd niet gezond (status: ${state:-onbekend}). Bekijk de logs hierboven of: docker compose logs"
}
wait_healthy

DIR_Q="$(printf '%q' "$DIR")"
cat <<MSG

Klaar. Wisselweer draait op http://127.0.0.1:8000 (alleen lokaal; er is geen poort of firewall aangepast).
MSG
if [[ $NEW_ENV -eq 1 ]]; then
  echo "Nieuw .env met gegenereerde geheime sleutel: $DIR/.env (rechten 600; bewaar het veilig)."
fi
if [[ $EXISTING -eq 1 ]]; then
  echo "Bijgewerkt. Je bestaande .env en gegevens zijn ongewijzigd; back-ups staan in $DIR/backups."
else
  cat <<MSG

Volgende stap: maak de beheerder aan (wachtwoord minimaal 10 tekens), in de installatiemap:
  cd $DIR_Q
  docker compose exec wisselweer wisselweer create-admin --username <naam>
Daarna kun je inloggen op http://127.0.0.1:8000.
MSG
fi
cat <<MSG

Meer: toegang op afstand, publiceren via SFTP (profiel 'publish'), back-up en herstel staan in
docs/install-docker.md (https://github.com/$REPO/blob/main/docs/install-docker.md).
Alleen via een VPN of reverse proxy met extra authenticatie van buiten bereikbaar maken.
MSG
