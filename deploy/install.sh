#!/usr/bin/env bash
# Wisselweer: native installatie op Debian 13 (trixie) en Ubuntu 24.04/26.04 LTS (ook in een LXC).
# Idempotent; uitvoeren als root (in een LXC is er vaak geen sudo):
#   ./deploy/install.sh                      # broncode uit deze repository
#   ./deploy/install.sh /pad/naar/wisselweer # of een andere map
#   ./deploy/install.sh https://host/repo.git [ref]
#
# Keuzes:
# - uv komt uit de release-tarball van GitHub (vaste versie, gecontroleerd met het .sha256-bestand
#   van dezelfde release, naar /usr/local/bin); de systeem-Python doet er niet toe, uv haalt
#   Python 3.12 naar /opt/wisselweer/python.
# - Opent geen poorten en wijzigt geen firewall. De service luistert op 127.0.0.1.
set -euo pipefail

# Vast: bewust niet overschrijfbaar via de omgeving. Bij een nieuwe versie hoort ook de uv-versie in
# .github/workflows/ci.yml mee te gaan.
readonly UV_VERSION="0.13.6"
APP_DIR=/opt/wisselweer
DATA_DIR=/var/lib/wisselweer
ETC_DIR=/etc/wisselweer
ENV_FILE="$ETC_DIR/wisselweer.env"
SVC_USER=wisselweer

if [[ $EUID -ne 0 ]]; then
  echo "Voer dit script uit als root." >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${1:-$(dirname "$HERE")}"
REF="${2:-}"
IS_GIT=0
if [[ "$SOURCE" =~ ^(https?://|git@|ssh://) ]]; then IS_GIT=1; fi

export DEBIAN_FRONTEND=noninteractive
PKGS=(python3 curl ca-certificates openssh-client sqlite3)
if [[ $IS_GIT -eq 1 ]]; then PKGS+=(git); fi
echo "==> Pakketten installeren: ${PKGS[*]}"
apt-get update -qq
apt-get install -y --no-install-recommends "${PKGS[@]}"

echo "==> Systeemgebruiker $SVC_USER"
if ! id -u "$SVC_USER" >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$DATA_DIR" --no-create-home \
    --shell /usr/sbin/nologin "$SVC_USER"
fi

echo "==> Mappen en rechten"
install -d -m 0755 -o root -g root "$APP_DIR"
install -d -m 0750 -o "$SVC_USER" -g "$SVC_USER" "$DATA_DIR"
install -d -m 0750 -o root -g "$SVC_USER" "$ETC_DIR"
# Voor de SFTP-publicatiesleutel en known_hosts.
install -d -m 0700 -o "$SVC_USER" -g "$SVC_USER" "$DATA_DIR/.ssh"
# Voertuigfoto's; wisselweer-publish.service ziet deze map niet.
install -d -m 0700 -o "$SVC_USER" -g "$SVC_USER" "$DATA_DIR/photos"

# Vast pad: /usr/local/bin staat niet in elke root-sessie (bv. `pct enter`) in PATH.
UV=/usr/local/bin/uv
export PATH="/usr/local/bin:$PATH"
if [[ ! -x "$UV" ]] || [[ "$("$UV" --version | awk '{print $2}')" != "$UV_VERSION" ]]; then
  echo "==> uv $UV_VERSION installeren naar /usr/local/bin"
  case "$(uname -m)" in
    x86_64) UV_ARCH=x86_64 ;;
    aarch64 | arm64) UV_ARCH=aarch64 ;;
    *) echo "Niet-ondersteunde architectuur voor uv: $(uname -m)" >&2; exit 1 ;;
  esac
  UV_NAME="uv-$UV_ARCH-unknown-linux-gnu"
  UV_BASE="https://github.com/astral-sh/uv/releases/download/$UV_VERSION"
  UV_TMP="$(mktemp -d)"
  (
    cd "$UV_TMP"
    curl --proto '=https' --tlsv1.2 -fsSL -o "$UV_NAME.tar.gz" "$UV_BASE/$UV_NAME.tar.gz"
    curl --proto '=https' --tlsv1.2 -fsSL -o "$UV_NAME.tar.gz.sha256" "$UV_BASE/$UV_NAME.tar.gz.sha256"
    # Het .sha256-bestand verwijst naar de bestandsnaam van de tarball (in deze map).
    sha256sum -c "$UV_NAME.tar.gz.sha256"
    tar -xzf "$UV_NAME.tar.gz"
    install -m 0755 -o root -g root "$UV_NAME/uv" "$UV_NAME/uvx" /usr/local/bin/
  )
  rm -rf "$UV_TMP"
fi

echo "==> Broncode naar $APP_DIR"
TMP_SRC=""
cleanup() { if [[ -n "$TMP_SRC" ]]; then rm -rf "$TMP_SRC"; fi; }
trap cleanup EXIT
if [[ $IS_GIT -eq 1 ]]; then
  TMP_SRC="$(mktemp -d)"
  git clone --quiet "$SOURCE" "$TMP_SRC/src"
  if [[ -n "$REF" ]]; then git -C "$TMP_SRC/src" checkout --quiet "$REF"; fi
  SRC_DIR="$TMP_SRC/src"
else
  SRC_DIR="$(cd "$SOURCE" && pwd)"
fi
for f in pyproject.toml uv.lock README.md src .env.example; do
  [[ -e "$SRC_DIR/$f" ]] || { echo "Ontbreekt in bron: $f" >&2; exit 1; }
done
umask 022
rm -rf "$APP_DIR/src"
cp -R "$SRC_DIR/src" "$APP_DIR/src"
cp "$SRC_DIR/pyproject.toml" "$SRC_DIR/uv.lock" "$SRC_DIR/README.md" "$SRC_DIR/.env.example" "$APP_DIR/"
find "$APP_DIR/src" -name __pycache__ -prune -exec rm -rf {} +

echo "==> Afhankelijkheden (uv sync --frozen --no-dev) en Python 3.12"
(
  cd "$APP_DIR"
  export UV_PYTHON_INSTALL_DIR="$APP_DIR/python"
  export UV_PYTHON_PREFERENCE=managed
  export UV_PROJECT_ENVIRONMENT="$APP_DIR/.venv"
  export UV_CACHE_DIR=/var/cache/wisselweer-uv
  "$UV" sync --frozen --no-dev --no-editable --python 3.12
)
chown -R root:root "$APP_DIR"
chmod -R go+rX,go-w "$APP_DIR"

NEW_ENV=0
if [[ ! -f "$ENV_FILE" ]]; then
  echo "==> $ENV_FILE aanmaken (bestond nog niet)"
  SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  sed -e "s|^WISSELWEER_DATA_DIR=.*|WISSELWEER_DATA_DIR=$DATA_DIR|" \
      -e "s|^WISSELWEER_HOST=.*|WISSELWEER_HOST=127.0.0.1|" \
      -e "s|^WISSELWEER_SECRET_KEY=.*|WISSELWEER_SECRET_KEY=$SECRET|" \
      "$APP_DIR/.env.example" > "$ENV_FILE"
  chown root:"$SVC_USER" "$ENV_FILE"
  chmod 0640 "$ENV_FILE"
  NEW_ENV=1
else
  echo "==> $ENV_FILE bestaat al; niet overschreven"
fi

echo "==> systemd-units installeren"
for u in wisselweer.service wisselweer-publish.service wisselweer-publish.timer; do
  install -m 0644 -o root -g root "$HERE/$u" "/etc/systemd/system/$u"
done
systemctl daemon-reload
systemctl enable wisselweer.service >/dev/null
systemctl restart wisselweer.service

echo "==> CLI: wisselweer (als servicegebruiker met het env-bestand)"
install -m 0755 -o root -g root "$HERE/wisselweer-cli.sh" /usr/local/bin/wisselweer
# /usr/local/bin staat niet in elke root-sessie (bv. `pct enter`) in PATH; een link in /usr/bin
# maakt `wisselweer` overal beschikbaar. Een bestaand bestand dat niet van ons is, blijft staan.
if [[ ! -e /usr/bin/wisselweer || "$(readlink /usr/bin/wisselweer)" == /usr/local/bin/wisselweer ]]; then
  ln -sfn /usr/local/bin/wisselweer /usr/bin/wisselweer
fi

cat <<MSG

Klaar. Wisselweer luistert op http://127.0.0.1:8000 (alleen lokaal; geen poorten of firewall aangepast).
$( [[ $NEW_ENV -eq 1 ]] && echo "Nieuw env-bestand met gegenereerde geheime sleutel: $ENV_FILE" )

Volgende stappen:
  1. Pas $ENV_FILE aan (minstens WISSELWEER_CONTACT) en herstart: systemctl restart wisselweer
     Draait de app achter een https-proxy (bv. Nginx Proxy Manager)? Zet dan ook
       WISSELWEER_COOKIE_SECURE=true
     en WISSELWEER_HOST=0.0.0.0 (met poort 8000 beperkt tot het proxy-IP; zie docs/install-lxc.md).
     Zonder die cookie-instelling gaat de sessiecookie ook over plain http.
  2. Maak de beheerder aan (wachtwoord minimaal 10 tekens):
       wisselweer create-admin --username <naam>
     Het commando \`wisselweer\` draait als $SVC_USER met $ENV_FILE, net als de service.
  3. Publiceren via SFTP: zie docs/install-lxc.md (sleutel maken in $DATA_DIR/.ssh, hostsleutel
     in known_hosts, WISSELWEER_PUBLISH_SFTP_* instellen). Testen:
       systemctl start wisselweer-publish.service; journalctl -u wisselweer-publish -n 30
     Plannen (SFTP): systemctl enable --now wisselweer-publish.timer. Gebruik hiervoor niet
     WISSELWEER_PUBLISH_INTERVAL_HOURS: de webapp heeft geen toegang tot $DATA_DIR/.ssh.
  4. Logs: journalctl -u wisselweer -f
MSG
