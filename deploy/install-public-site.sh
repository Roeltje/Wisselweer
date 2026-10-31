#!/usr/bin/env bash
# Wisselweer - installatie van de publieke statische site op een kale
# Debian 13 (trixie) LXC/VM (werkt ook op Ubuntu 24.04/26.04).
#
# Idempotent: opnieuw draaien is veilig; bestaande configs worden eerst
# gebackupt als <bestand>.bak.<datum>. Zie docs/public-site.md.
set -euo pipefail

# ----------------------------------------------------------------- helpers
c_reset=$'\033[0m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_red=$'\033[31m'; c_blu=$'\033[34m'
if [ ! -t 1 ]; then c_reset=""; c_grn=""; c_yel=""; c_red=""; c_blu=""; fi
info() { printf '%s==>%s %s\n' "$c_blu" "$c_reset" "$*"; }
ok()   { printf '  %s[ok]%s %s\n' "$c_grn" "$c_reset" "$*"; }
warn() { printf '  %s[let op]%s %s\n' "$c_yel" "$c_reset" "$*" >&2; WARNINGS+=("$*"); }
die()  { printf '%s[fout]%s %s\n' "$c_red" "$c_reset" "$*" >&2; exit 1; }
WARNINGS=()

usage() {
  cat <<'EOF'
Gebruik: install-public-site.sh --proxy-ip <ip> [opties]

Richt een kale Debian 13 (of Ubuntu 24.04+) container in als statische
webserver voor de publieke Wisselweer-site (nginx + SFTP-only deploy-gebruiker
in een chroot + nftables-firewall). Moet als root draaien.

Verplicht:
  --proxy-ip <ip>        IP van de reverse proxy (bv. Nginx Proxy Manager).
                         Alleen dit IP mag poort 80; ook set_real_ip_from.

Opties (flag of omgevingsvariabele):
  --domain <naam>        server_name (ook www.<naam>)     [WW_DOMAIN, default wisselweer.nl]
  --ssh-allow <ip,ip>    wie op poort 22 mag              [WW_SSH_ALLOW]
                         Leeg => firewall wordt NIET geactiveerd (anti-lockout).
  --deny-out <ip,ip>     uitgaand blokkeren naar deze IP's (nieuwe verbindingen;
                         antwoorden op inkomend verkeer blijven werken)  [WW_DENY_OUT]
  --deploy-key "<key>"   publieke ssh-sleutel voor gebruiker deploy; herhaalbaar [WW_DEPLOY_KEY]
  --deploy-key-file <p>  bestand met publieke sleutel(s); herhaalbaar  [WW_DEPLOY_KEY_FILE]
  --site-src <pad|url>   kopieer initiële sitebestanden: een map (bij voorkeur
                         <repo>/public-site) of git-URL met een public-site/ map.
                         Zonder: minimale placeholder-index.       [WW_SITE_SRC]
  --force-firewall       activeer firewall ook als jouw huidige SSH-adres niet
                         in --ssh-allow staat (op eigen risico)
  --no-firewall          sla de firewall over
  -h, --help             deze hulp

IP's zijn IPv4-adressen of -bereiken (bv. 192.0.2.10 of 192.0.2.0/24).

Voorbeeld:
  sudo ./install-public-site.sh --domain wisselweer.nl --proxy-ip 192.0.2.10 \
    --ssh-allow 192.0.2.20,192.0.2.5 --deny-out 192.0.2.20 \
    --deploy-key-file /root/deploy.pub --site-src /root/Wisselweer/public-site
EOF
}

# ------------------------------------------------------------ parameters
DOMAIN="${WW_DOMAIN:-wisselweer.nl}"
PROXY_IP="${WW_PROXY_IP:-}"
SSH_ALLOW="${WW_SSH_ALLOW:-}"
DENY_OUT="${WW_DENY_OUT:-}"
SITE_SRC="${WW_SITE_SRC:-}"
FORCE_FW=0
NO_FW=0
DEPLOY_KEYS=()
DEPLOY_KEY_FILES=()
[ -n "${WW_DEPLOY_KEY:-}" ] && DEPLOY_KEYS+=("$WW_DEPLOY_KEY")
[ -n "${WW_DEPLOY_KEY_FILE:-}" ] && DEPLOY_KEY_FILES+=("$WW_DEPLOY_KEY_FILE")

# --vlag=waarde => --vlag waarde
ARGS=()
for a in "$@"; do
  case "$a" in
    --*=*) ARGS+=("${a%%=*}" "${a#*=}") ;;
    *) ARGS+=("$a") ;;
  esac
done
set -- ${ARGS[@]+"${ARGS[@]}"}

need_val() { [ "$#" -ge 2 ] && [ -n "$2" ] || die "Optie $1 vereist een waarde (zie --help)."; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --domain)         need_val "$@"; DOMAIN="$2"; shift 2 ;;
    --proxy-ip)       need_val "$@"; PROXY_IP="$2"; shift 2 ;;
    --ssh-allow)      need_val "$@"; SSH_ALLOW="$2"; shift 2 ;;
    --deny-out)       need_val "$@"; DENY_OUT="$2"; shift 2 ;;
    --deploy-key)     need_val "$@"; DEPLOY_KEYS+=("$2"); shift 2 ;;
    --deploy-key-file) need_val "$@"; DEPLOY_KEY_FILES+=("$2"); shift 2 ;;
    --site-src)       need_val "$@"; SITE_SRC="$2"; shift 2 ;;
    --force-firewall) FORCE_FW=1; shift ;;
    --no-firewall)    NO_FW=1; shift ;;
    -h|--help)        usage; exit 0 ;;
    *) usage >&2; die "Onbekende optie: $1" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "Dit script moet als root draaien (sudo)."
[ -n "$PROXY_IP" ] || { usage >&2; die "--proxy-ip is verplicht."; }

# --------------------------------------------------------------- validatie
IP_RE='^([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?$'
valid_ip() {
  local ip="${1%%/*}" o IFS=.
  [[ "$1" =~ $IP_RE ]] || return 1
  for o in $ip; do [ "$o" -le 255 ] || return 1; done
  if [[ "$1" == */* ]]; then [ "${1#*/}" -le 32 ] || return 1; fi
}
# normaliseer "a, b,c" => "a, b, c" (nft-set-inhoud); leeg => leeg
norm_list() {
  local raw="$1" item out="" IFS=,
  for item in $raw; do
    item="${item//[[:space:]]/}"
    [ -z "$item" ] && continue
    valid_ip "$item" || die "Ongeldig IP-adres of -bereik: '$item'"
    out="${out:+$out, }$item"
  done
  printf '%s' "$out"
}
[[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || die "Ongeldige domeinnaam: '$DOMAIN'"
PROXY_IP="${PROXY_IP//[[:space:]]/}"
valid_ip "$PROXY_IP" || die "Ongeldig --proxy-ip: '$PROXY_IP'"
SSH_ALLOW="$(norm_list "$SSH_ALLOW")"
DENY_OUT="$(norm_list "$DENY_OUT")"

STAMP="$(date +%Y%m%d%H%M%S)"
TMPDIR_WW="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_WW"' EXIT

# Installeer inhoud van $1 (tijdelijk bestand) als $2 met modus $3.
# Backup van een bestaand, afwijkend bestand. Zet LAST_BACKUP ("" = was nieuw,
# "same" = ongewijzigd) zodat de aanroeper kan terugdraaien.
LAST_BACKUP=""
install_file() {
  local src="$1" dest="$2" mode="$3"
  if [ -f "$dest" ] && cmp -s "$src" "$dest"; then
    LAST_BACKUP="same"; ok "$dest ongewijzigd"; return 0
  fi
  LAST_BACKUP=""
  if [ -e "$dest" ]; then
    LAST_BACKUP="$dest.bak.$STAMP"
    cp -a "$dest" "$LAST_BACKUP"
    ok "backup: $LAST_BACKUP"
  fi
  install -m "$mode" -o root -g root "$src" "$dest"
  ok "geschreven: $dest"
}
rollback_file() { # $1 = dest
  if [ -n "$LAST_BACKUP" ] && [ "$LAST_BACKUP" != "same" ]; then mv -f "$LAST_BACKUP" "$1"
  elif [ -z "$LAST_BACKUP" ]; then rm -f "$1"; fi
}

# ------------------------------------------------------------- 1. pakketten
info "1/7 Pakketten installeren"
export DEBIAN_FRONTEND=noninteractive
APT_OPTS=(-y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)
apt-get update -qq
apt-get "${APT_OPTS[@]}" -qq full-upgrade

NGINX_PKG="nginx"
if dpkg -s nginx >/dev/null 2>&1 || dpkg -s nginx-light >/dev/null 2>&1; then
  NGINX_PKG=""   # al aanwezig; niet wisselen
elif apt-cache show nginx-light >/dev/null 2>&1; then
  NGINX_PKG="nginx-light"
fi
PKGS=(openssh-server nftables unattended-upgrades curl ca-certificates)
[ -n "$NGINX_PKG" ] && PKGS+=("$NGINX_PKG")
case "$SITE_SRC" in *://*|git@*|*.git) PKGS+=(git) ;; esac
apt-get "${APT_OPTS[@]}" -qq install "${PKGS[@]}"
ok "geïnstalleerd: ${PKGS[*]}"

cat >"$TMPDIR_WW/20auto-upgrades" <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
install_file "$TMPDIR_WW/20auto-upgrades" /etc/apt/apt.conf.d/20auto-upgrades 644
ok "unattended-upgrades staat aan"

# --------------------------------------------- 2. mappen en deploy-gebruiker
info "2/7 Mappen en gebruiker 'deploy' (SFTP-only, chroot)"
if id -u deploy >/dev/null 2>&1; then
  usermod --home /srv/wisselweer --shell /usr/sbin/nologin deploy
  ok "gebruiker deploy bestond al (shell/home bijgewerkt)"
else
  useradd --system --user-group --home-dir /srv/wisselweer --shell /usr/sbin/nologin deploy
  ok "gebruiker deploy aangemaakt"
fi
mkdir -p /srv/wisselweer/site
chown root:root /srv/wisselweer && chmod 755 /srv/wisselweer      # chroot-root: root-eigendom, verplicht
chown deploy:www-data /srv/wisselweer/site && chmod 2755 /srv/wisselweer/site
ok "/srv/wisselweer (root:root 755) en /srv/wisselweer/site (deploy:www-data 2755)"

# ------------------------------------------------------------ 3. SSH-sleutels
info "3/7 Deploy-sleutel(s) en sshd"
KEYS_TMP="$TMPDIR_WW/authorized_keys"
: >"$KEYS_TMP"
add_key() {
  local k="$1"
  k="${k%$'\r'}"
  [ -z "${k//[[:space:]]/}" ] && return 0
  case "$k" in \#*) return 0 ;; esac
  case "$k" in
    ssh-ed25519\ *|ssh-rsa\ *|ecdsa-sha2-*|sk-ssh-ed25519@*|sk-ecdsa-sha2-*) ;;
    *) die "Dit lijkt geen publieke ssh-sleutel: '${k:0:30}...' (privé-sleutels hier nooit gebruiken)" ;;
  esac
  printf '%s\n' "$k" >>"$KEYS_TMP"
}
for k in ${DEPLOY_KEYS[@]+"${DEPLOY_KEYS[@]}"}; do add_key "$k"; done
for f in ${DEPLOY_KEY_FILES[@]+"${DEPLOY_KEY_FILES[@]}"}; do
  [ -r "$f" ] || die "Kan sleutelbestand niet lezen: $f"
  while IFS= read -r line || [ -n "$line" ]; do add_key "$line"; done <"$f"
done

mkdir -p /etc/ssh/authorized_keys
chown root:root /etc/ssh/authorized_keys && chmod 755 /etc/ssh/authorized_keys
if [ -s "$KEYS_TMP" ]; then
  sort -u "$KEYS_TMP" >"$KEYS_TMP.u"
  install_file "$KEYS_TMP.u" /etc/ssh/authorized_keys/deploy 644
  ok "$(wc -l <"$KEYS_TMP.u" | tr -d ' ') sleutel(s) voor deploy"
elif [ -s /etc/ssh/authorized_keys/deploy ]; then
  ok "geen nieuwe sleutels opgegeven; bestaande /etc/ssh/authorized_keys/deploy blijft"
else
  : >"$KEYS_TMP.u"
  install_file "$KEYS_TMP.u" /etc/ssh/authorized_keys/deploy 644
  warn "Geen --deploy-key opgegeven: deploy kan nog niet inloggen. Voeg later een publieke sleutel toe aan /etc/ssh/authorized_keys/deploy."
fi

mkdir -p /etc/ssh/sshd_config.d
if ! grep -Eqi '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/' /etc/ssh/sshd_config; then
  cp -a /etc/ssh/sshd_config "/etc/ssh/sshd_config.bak.$STAMP"
  { echo 'Include /etc/ssh/sshd_config.d/*.conf'; cat "/etc/ssh/sshd_config.bak.$STAMP"; } >/etc/ssh/sshd_config
  ok "Include voor sshd_config.d toegevoegd (backup: /etc/ssh/sshd_config.bak.$STAMP)"
fi

cat >"$TMPDIR_WW/10-wisselweer.conf" <<'EOF'
# Beheerd door deploy/install-public-site.sh
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password

Match User deploy
    AuthorizedKeysFile /etc/ssh/authorized_keys/deploy
    ChrootDirectory /srv/wisselweer
    ForceCommand internal-sftp -u 0022
    AllowTcpForwarding no
    X11Forwarding no
    PermitTTY no
EOF
install_file "$TMPDIR_WW/10-wisselweer.conf" /etc/ssh/sshd_config.d/10-wisselweer.conf 644
if [ "$LAST_BACKUP" != "same" ]; then
  if sshd -t; then
    systemctl enable ssh >/dev/null 2>&1 || systemctl enable sshd >/dev/null 2>&1 || true
    systemctl reload-or-restart ssh 2>/dev/null || systemctl reload-or-restart sshd
    ok "sshd getest (sshd -t) en herladen; bestaande sessies blijven open"
  else
    rollback_file /etc/ssh/sshd_config.d/10-wisselweer.conf
    die "sshd -t faalt; sshd-configuratie teruggedraaid. Er is niets herstart."
  fi
else
  systemctl enable ssh >/dev/null 2>&1 || systemctl enable sshd >/dev/null 2>&1 || true
fi
warn "Wachtwoordlogin is nu uit voor ALLE gebruikers. Zorg dat je zelf een sleutel hebt voordat je deze sessie sluit."

# ----------------------------------------------------------------- 4. nginx
info "4/7 nginx"
cat >"$TMPDIR_WW/nginx-site.tpl" <<'EOF'
# Beheerd door deploy/install-public-site.sh
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name @DOMAIN@ www.@DOMAIN@;
    root /srv/wisselweer/site;
    index index.html;
    error_page 404 /404.html;

    # Echte bezoeker-IP via de reverse proxy
    set_real_ip_from @PROXY_IP@;
    real_ip_header X-Forwarded-For;

    server_tokens off;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
    add_header X-Frame-Options DENY always;
    add_header Permissions-Policy "geolocation=(), camera=(), microphone=()" always;
    add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'" always;

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;

    # Advies: kort cachen zodat updates snel zichtbaar zijn
    location = /advice.json {
        add_header Cache-Control "public, max-age=300, must-revalidate" always;
        add_header X-Content-Type-Options nosniff always;
        try_files $uri =404;
    }

    # Statische assets lang cachen
    location ~* \.(css|js|svg|png|ico|webmanifest|woff2)$ {
        add_header Cache-Control "public, max-age=604800" always;
        add_header X-Content-Type-Options nosniff always;
        try_files $uri =404;
    }

    location / {
        try_files $uri $uri/ =404;
    }

    # Geen verborgen bestanden of tijdelijke uploads serveren
    location ~ /\.            { deny all; }
    location ~ \.tmp$         { deny all; }
}
EOF
tpl="$(cat "$TMPDIR_WW/nginx-site.tpl")"
tpl="${tpl//@DOMAIN@/$DOMAIN}"
tpl="${tpl//@PROXY_IP@/$PROXY_IP}"
printf '%s\n' "$tpl" >"$TMPDIR_WW/nginx-site.conf"

mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
install_file "$TMPDIR_WW/nginx-site.conf" /etc/nginx/sites-available/wisselweer 644
NGINX_BAK="$LAST_BACKUP"
DEFAULT_LINK_TARGET=""
if [ -e /etc/nginx/sites-enabled/default ] || [ -L /etc/nginx/sites-enabled/default ]; then
  DEFAULT_LINK_TARGET="$(readlink /etc/nginx/sites-enabled/default || true)"
  rm -f /etc/nginx/sites-enabled/default
  ok "default-site uitgeschakeld"
fi
ln -sfn /etc/nginx/sites-available/wisselweer /etc/nginx/sites-enabled/wisselweer
if nginx -t 2>"$TMPDIR_WW/nginx-t.log"; then
  systemctl enable nginx >/dev/null 2>&1 || true
  systemctl reload nginx 2>/dev/null || systemctl restart nginx
  ok "nginx -t geslaagd en nginx herladen"
else
  cat "$TMPDIR_WW/nginx-t.log" >&2
  LAST_BACKUP="$NGINX_BAK"; rollback_file /etc/nginx/sites-available/wisselweer
  [ -n "$DEFAULT_LINK_TARGET" ] && ln -sfn "$DEFAULT_LINK_TARGET" /etc/nginx/sites-enabled/default
  [ -e /etc/nginx/sites-available/wisselweer ] || rm -f /etc/nginx/sites-enabled/wisselweer
  die "nginx -t faalt; wijziging teruggedraaid."
fi

# ----------------------------------------------------------- 5. sitebestanden
info "5/7 Sitebestanden"
SITE_DIR=/srv/wisselweer/site
copy_site() { # $1 = bronmap
  local src="$1" keep=()
  [ -d "$src" ] || die "Bronmap bestaat niet: $src"
  [ -f "$src/index.html" ] || die "Geen index.html in $src (verwacht de inhoud van public-site/)."
  # Een bestaande advice.json (live advies) nooit overschrijven.
  [ -f "$SITE_DIR/advice.json" ] && keep=(--exclude=./advice.json)
  (cd "$src" && tar cf - ${keep[@]+"${keep[@]}"} .) | tar xf - -C "$SITE_DIR" --no-same-owner --no-same-permissions
  if [ "${#keep[@]}" -gt 0 ]; then ok "bestaande advice.json behouden"; fi
  ok "sitebestanden gekopieerd uit $src"
}
if [ -n "$SITE_SRC" ]; then
  src="$SITE_SRC"
  case "$SITE_SRC" in
    *://*|git@*|*.git)
      command -v git >/dev/null || die "git ontbreekt"
      git clone --depth 1 --quiet "$SITE_SRC" "$TMPDIR_WW/repo"
      src="$TMPDIR_WW/repo" ;;
  esac
  [ -d "$src/public-site" ] && src="$src/public-site"
  copy_site "$src"
elif [ ! -f "$SITE_DIR/index.html" ]; then
  cat >"$SITE_DIR/index.html" <<'EOF'
<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wisselweer</title>
</head>
<body>
<h1>Wisselweer</h1>
<p>Deze site wordt binnenkort ingericht.</p>
</body>
</html>
EOF
  ok "placeholder-index geplaatst (geen --site-src opgegeven)"
else
  ok "bestaande sitebestanden blijven staan"
fi
chown -R deploy:www-data "$SITE_DIR"
find "$SITE_DIR" -type d -exec chmod 2755 {} +
find "$SITE_DIR" -type f -exec chmod 644 {} +

# ------------------------------------------------------------- 6. firewall
info "6/7 Firewall (nftables)"
FW_ACTIVE=0
fw_skip() { warn "$1"; }
if [ "$NO_FW" -eq 1 ]; then
  fw_skip "Firewall overgeslagen (--no-firewall)."
elif [ -z "$SSH_ALLOW" ]; then
  fw_skip "--ssh-allow is leeg: firewall NIET geactiveerd, anders sluit je jezelf buiten. Draai het script opnieuw met --ssh-allow <jouw-ip>."
else
  # Anti-lockout: zit je nu via SSH, dan moet jouw adres in --ssh-allow staan.
  proceed=1
  if [ -n "${SSH_CONNECTION:-}" ]; then
    my_ip="${SSH_CONNECTION%% *}"
    found=0; uncertain=0
    IFS=',' read -r -a allow_arr <<<"${SSH_ALLOW//[[:space:]]/}"
    for e in "${allow_arr[@]}"; do
      [ "$e" = "$my_ip" ] && found=1
      case "$e" in */*) uncertain=1 ;; esac
    done
    if [ "$found" -eq 0 ] && [ "$uncertain" -eq 0 ] && [ "$FORCE_FW" -eq 0 ]; then
      proceed=0
      fw_skip "Je zit via SSH vanaf $my_ip, dat niet in --ssh-allow staat: firewall NIET geactiveerd. Voeg het toe of gebruik --force-firewall."
    elif [ "$found" -eq 0 ] && [ "$uncertain" -eq 1 ]; then
      warn "Kon niet controleren of $my_ip in een --ssh-allow-bereik valt; controleer dit zelf."
    fi
  fi
  if [ "$proceed" -eq 1 ]; then
    {
      echo '#!/usr/sbin/nft -f'
      echo '# Beheerd door deploy/install-public-site.sh'
      echo 'flush ruleset'
      echo 'table inet filter {'
      echo '  chain input {'
      echo '    type filter hook input priority 0; policy drop;'
      echo '    iif lo accept'
      echo '    ct state established,related accept'
      echo '    ct state invalid drop'
      echo "    ip saddr { $PROXY_IP } tcp dport 80 accept"
      echo "    ip saddr { $SSH_ALLOW } tcp dport 22 accept"
      echo '    icmp type echo-request accept'
      echo '    icmpv6 type { echo-request, nd-neighbor-solicit, nd-neighbor-advert, nd-router-solicit, nd-router-advert } accept'
      echo '    udp sport 67 udp dport 68 accept'
      echo '  }'
      echo '  chain output {'
      echo '    type filter hook output priority 0; policy accept;'
      echo '    oif lo accept'
      echo '    ct state established,related accept'
      [ -n "$DENY_OUT" ] && echo "    ip daddr { $DENY_OUT } drop"
      echo '  }'
      echo '}'
    } >"$TMPDIR_WW/nftables.conf"
    if nft -c -f "$TMPDIR_WW/nftables.conf"; then
      install_file "$TMPDIR_WW/nftables.conf" /etc/nftables.conf 755
      nft -f /etc/nftables.conf
      systemctl enable nftables >/dev/null 2>&1 || true
      FW_ACTIVE=1
      ok "firewall actief: poort 80 alleen van $PROXY_IP, poort 22 alleen van $SSH_ALLOW"
      [ -n "$DENY_OUT" ] && ok "uitgaand verkeer naar $DENY_OUT geblokkeerd"
    else
      fw_skip "nft -c -f keurde de regels af: firewall NIET geactiveerd."
    fi
  fi
fi

# ---------------------------------------------------------------- 7. test
info "7/7 Zelftest"
if hdrs="$(curl -sS -m 5 -I -H "Host: $DOMAIN" http://127.0.0.1/ 2>&1)"; then
  echo "$hdrs" | head -1 | grep -q ' 200' && ok "nginx antwoordt 200 op http://127.0.0.1/" || warn "Onverwacht antwoord van nginx: $(echo "$hdrs" | head -1)"
  echo "$hdrs" | grep -qi '^content-security-policy' && ok "CSP-header aanwezig" || warn "CSP-header ontbreekt"
else
  warn "curl naar nginx mislukte: $hdrs"
fi

# -------------------------------------------------------------- samenvatting
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"; HOST_IP="${HOST_IP:-<ip-van-deze-container>}"
echo
printf '%s================ Klaar ================%s\n' "$c_grn" "$c_reset"
echo "Domein:        $DOMAIN (+ www.$DOMAIN)"
echo "Webroot:       /srv/wisselweer/site (SFTP-pad: /site)"
echo "Poort 80:      alleen van $PROXY_IP $( [ "$FW_ACTIVE" -eq 1 ] && echo '(afgedwongen)' || echo '(firewall NIET actief)')"
echo "Poort 22:      ${SSH_ALLOW:-<niet beperkt>} $( [ "$FW_ACTIVE" -eq 1 ] && echo '(afgedwongen)' || echo '(firewall NIET actief)')"
echo "Config:        /etc/nginx/sites-available/wisselweer, /etc/ssh/sshd_config.d/10-wisselweer.conf, /etc/nftables.conf"
if [ "${#WARNINGS[@]}" -gt 0 ]; then
  echo; printf '%sPunten van aandacht:%s\n' "$c_yel" "$c_reset"
  for w in "${WARNINGS[@]}"; do echo "  - $w"; done
fi
cat <<EOF

Controle (vanaf de proxy-host, resp. vanaf een toegestaan beheer-IP):
  curl -sI http://$HOST_IP/ | head -5
  sftp -i ~/.ssh/<deploy-sleutel> deploy@$HOST_IP        # moet alleen /site tonen
  ssh  -i ~/.ssh/<deploy-sleutel> deploy@$HOST_IP        # moet weigeren (geen shell)
  Hostkey voor de privé-app (StrictHostKeyChecking=yes):
    ssh-keyscan -t ed25519 $HOST_IP >> <known_hosts van de wisselweer-gebruiker>

Nog te doen buiten deze container (details: docs/public-site.md, sectie
"Installatie op een eigen LXC"):
  1. Nginx Proxy Manager: Proxy Host $DOMAIN + www.$DOMAIN -> http://$HOST_IP:80,
     Let's Encrypt via DNS-challenge (Cloudflare-token met alleen Zone > DNS > Edit),
     Force SSL aan.
  2. Cloudflare: DNS proxied (oranje wolk), SSL/TLS = Full (strict), cache-regel
     voor /advice.json met Edge TTL <= 5 minuten (respect origin).
  3. Privé-app: WISSELWEER_PUBLISH_SFTP_* instellen (zie docs/publishing.md) en
     'wisselweer publish' testen.
EOF
