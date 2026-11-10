#!/usr/bin/env bash
# Stats Collector installer for Debian 13 (Trixie). Idempotent: safe to run again to repair or reconfigure.
#
#   curl -fsSL https://raw.githubusercontent.com/rhisijmuiden/stats-collector/develop/install.sh | bash
#   bash install.sh --channel test --public-url https://stats.example.org --proxy-ips 192.0.2.10 -y
#
# Options:
#   --channel test|production   update channel (default: test during the development phase)
#   --public-url URL            URL users open, e.g. https://stats.example.org
#   --proxy-ips LIST            comma separated reverse proxy IPs that may send X-Forwarded-* headers
#   --port N                    web port (default 8080)
#   --listen ADDR               listen address (default 0.0.0.0; use 127.0.0.1 when the proxy runs on this host)
#   --source DIR                install from a local source checkout instead of a GitHub release
#   --tarball FILE              install from a local release tarball
#   --firewall                  configure nftables: allow SSH everywhere, the web port only from the proxy IPs
#   -y, --yes                   non-interactive, accept defaults
set -euo pipefail

REPO="rhisijmuiden/stats-collector"
APP_USER="statscollector"
INSTALL_DIR="/opt/stats-collector"
DATA_DIR="/var/lib/stats-collector"
CONF_DIR="/etc/stats-collector"
CONF="$CONF_DIR/config.env"
LOG_DIR="/var/log/stats-collector"
STANZA="stats-collector"
DB_NAME="statscollector"
DB_USER="statscollector"

CHANNEL=""
PUBLIC_URL=""
PROXY_IPS=""
PORT=""
LISTEN=""
SOURCE=""
TARBALL=""
FIREWALL=0
YES=0

# A UTF-8 locale for everything we start (PostgreSQL clusters created under LANG=C would be SQL_ASCII).
export LANG=C.UTF-8 LC_ALL=C.UTF-8

c_ok=$'\e[32m'; c_warn=$'\e[33m'; c_err=$'\e[31m'; c_b=$'\e[1m'; c_0=$'\e[0m'
step() { echo; echo "${c_b}==> $*${c_0}"; }
ok() { echo "${c_ok}✓${c_0} $*"; }
warn() { echo "${c_warn}!${c_0} $*"; }
die() { echo "${c_err}✗ $*${c_0}" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --channel) CHANNEL="$2"; shift 2 ;;
    --public-url) PUBLIC_URL="$2"; shift 2 ;;
    --proxy-ips) PROXY_IPS="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --listen) LISTEN="$2"; shift 2 ;;
    --source) SOURCE="$(cd "$2" && pwd)"; shift 2 ;;
    --tarball) TARBALL="$(readlink -f "$2")"; shift 2 ;;
    --firewall) FIREWALL=1; shift ;;
    -y|--yes) YES=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

# Reading answers works even when the script is piped into bash.
ask() { # ask VAR "question" default
  local var="$1" q="$2" def="$3" ans=""
  if [ -n "${!var}" ]; then return; fi
  if [ "$YES" = 1 ] || ! [ -r /dev/tty ]; then printf -v "$var" '%s' "$def"; return; fi
  read -r -p "$q [$def]: " ans < /dev/tty || true
  printf -v "$var" '%s' "${ans:-$def}"
}

conf_get() { [ -f "$CONF" ] && grep -E "^$1=" "$CONF" | tail -1 | cut -d= -f2- || true; }

# ----------------------------------------------------------------------------------------------------------
step "Checking the system"
[ "$(id -u)" = 0 ] || die "Run as root (sudo bash install.sh)."
. /etc/os-release
[ "${ID:-}" = debian ] || die "This installer supports Debian only (found ${ID:-unknown})."
[ "${VERSION_ID:-}" = 13 ] || die "Debian 13 (Trixie) is required (found ${VERSION_ID:-unknown})."
ok "Debian $VERSION_ID ($VERSION_CODENAME)"
curl -fsS -o /dev/null --max-time 10 https://deb.debian.org || die "No network access to deb.debian.org."
ok "Network"

# Earlier answers are kept on re-runs.
CHANNEL="${CHANNEL:-$(conf_get SC_DEFAULT_CHANNEL)}"
PUBLIC_URL="${PUBLIC_URL:-$(conf_get SC_PUBLIC_URL)}"
PROXY_IPS="${PROXY_IPS:-$(conf_get SC_TRUSTED_PROXIES)}"
PORT="${PORT:-$(conf_get SC_PORT)}"
LISTEN="${LISTEN:-$(conf_get SC_HOST)}"

ask CHANNEL "Update channel (test/production)" "test"
[[ "$CHANNEL" =~ ^(test|production)$ ]] || die "Channel must be test or production."
ask PUBLIC_URL "Public URL (as users will open it)" "http://$(hostname -f 2>/dev/null || hostname):8080"
ask PROXY_IPS "Reverse proxy IP addresses (comma separated)" "127.0.0.1"
ask PORT "Web port" "8080"
ask LISTEN "Listen address" "0.0.0.0"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "Port must be a number."
[[ "$PROXY_IPS" =~ ^[0-9a-fA-F:.,/\ ]+$ ]] || die "Proxy IPs may only contain IP addresses, commas and CIDR ranges."
PROXY_IPS="${PROXY_IPS// /}"

# ----------------------------------------------------------------------------------------------------------
step "Installing packages from the Debian repositories"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
PKGS=(python3 python3-venv python3-pip postgresql postgresql-contrib redis-server pgbackrest rclone git curl
      ca-certificates tar gzip openssh-client jq)
[ -n "$SOURCE" ] && PKGS+=(nodejs npm)
[ "$FIREWALL" = 1 ] && PKGS+=(nftables)
apt-get install -y -qq "${PKGS[@]}" >/dev/null
PG_VER="$(ls /usr/lib/postgresql | sort -n | tail -1)"
ok "Python $(python3 -c 'import platform;print(platform.python_version())'), PostgreSQL $PG_VER, Redis, pgBackRest, rclone"
systemctl enable --now redis-server >/dev/null 2>&1 || true

# ----------------------------------------------------------------------------------------------------------
step "Creating user and directories"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$APP_USER"
install -d -m 755 "$INSTALL_DIR" "$INSTALL_DIR/releases"
# 711 on the data and backup folders: other users (postgres for pgBackRest) may pass through but not list them.
install -d -m 711 -o "$APP_USER" -g "$APP_USER" "$DATA_DIR"
install -d -m 750 -o "$APP_USER" -g "$APP_USER" "$DATA_DIR/uploads" "$LOG_DIR"
install -d -m 770 -o root -g "$APP_USER" "$DATA_DIR/ops"
install -d -m 711 -o root -g root "$DATA_DIR/backup"
install -d -m 750 -o root -g root "$DATA_DIR/backup/files" "$DATA_DIR/backup/manifests"
install -d -m 750 -o postgres -g postgres "$DATA_DIR/backup/pgbackrest" "$DATA_DIR/backup/pre-update"
install -d -m 750 -o root -g "$APP_USER" "$CONF_DIR"
ok "$INSTALL_DIR, $DATA_DIR, $CONF_DIR"

# ----------------------------------------------------------------------------------------------------------
step "Configuration"
rand() { python3 -c 'import secrets;print(secrets.token_urlsafe(36))'; }
SECRET_KEY="$(conf_get SC_SECRET_KEY)"; SECRET_KEY="${SECRET_KEY:-$(rand)}"
DB_URL="$(conf_get SC_DATABASE_URL)"
if [ -z "$DB_URL" ]; then
  DB_PASS="$(python3 -c 'import secrets;print(secrets.token_hex(24))')"
  DB_URL="postgresql+psycopg://$DB_USER:$DB_PASS@127.0.0.1:5432/$DB_NAME"
else
  DB_PASS="$(python3 -c 'import sys,urllib.parse as u;print(u.urlparse(sys.argv[1]).password or "")' "$DB_URL")"
fi
umask 027
cat > "$CONF.new" <<EOF
# Stats Collector configuration. Generated by install.sh; re-running the installer keeps these values.
SC_ENV=production
SC_DATABASE_URL=$DB_URL
SC_SECRET_KEY=$SECRET_KEY
SC_DATA_DIR=$DATA_DIR
SC_INSTALL_DIR=$INSTALL_DIR
SC_PUBLIC_URL=$PUBLIC_URL
SC_HOST=$LISTEN
SC_PORT=$PORT
SC_LIVEWALL_PORT=8081
SC_TRUSTED_PROXIES=$PROXY_IPS
SC_DEFAULT_CHANNEL=$CHANNEL
SC_GITHUB_REPO=$REPO
SC_PGBACKREST_STANZA=$STANZA
EOF
# keep any extra settings an administrator added by hand
if [ -f "$CONF" ]; then
  grep -E '^SC_' "$CONF" | while IFS= read -r line; do
    key="${line%%=*}"; grep -qE "^$key=" "$CONF.new" || echo "$line" >> "$CONF.new"
  done
fi
mv "$CONF.new" "$CONF"
chown root:"$APP_USER" "$CONF"; chmod 640 "$CONF"
umask 022
ok "$CONF"

# ----------------------------------------------------------------------------------------------------------
step "Database"
systemctl enable --now postgresql >/dev/null 2>&1
for _ in $(seq 1 30); do runuser -u postgres -- pg_isready -q && break; sleep 1; done
runuser -u postgres -- psql -qtAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 \
  || runuser -u postgres -- psql -qc "CREATE ROLE $DB_USER LOGIN"
runuser -u postgres -- psql -qc "ALTER ROLE $DB_USER WITH PASSWORD '$DB_PASS'"
ENC="$(runuser -u postgres -- psql -qtAc "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname='$DB_NAME'")"
if [ -n "$ENC" ] && [ "$ENC" != UTF8 ]; then
  # Happens when PostgreSQL was installed under a non-UTF-8 locale. Recreate the database if it is still empty.
  TABLES="$(runuser -u postgres -- psql -qtAc "SELECT count(*) FROM pg_tables WHERE schemaname='public'" -d "$DB_NAME")"
  [ "$TABLES" = 0 ] || die "Database $DB_NAME uses encoding $ENC instead of UTF8 and already contains data. Convert it manually."
  warn "Database $DB_NAME was created as $ENC; recreating it as UTF-8."
  runuser -u postgres -- dropdb "$DB_NAME"
  ENC=""
fi
[ -n "$ENC" ] || runuser -u postgres -- createdb -O "$DB_USER" -E UTF8 --locale=C.UTF-8 -T template0 "$DB_NAME"
ok "PostgreSQL database $DB_NAME (UTF-8)"

step "Backups (pgBackRest)"
PG_DATA="/var/lib/postgresql/$PG_VER/main"
install -d -m 750 -o postgres -g postgres /var/log/pgbackrest /etc/pgbackrest
cat > /etc/pgbackrest/pgbackrest.conf <<EOF
[global]
repo1-path=$DATA_DIR/backup/pgbackrest
repo1-retention-full=4
compress-type=zst
start-fast=y
log-level-console=info
log-level-file=detail

[$STANZA]
pg1-path=$PG_DATA
pg1-socket-path=/var/run/postgresql
EOF
chown postgres:postgres /etc/pgbackrest/pgbackrest.conf; chmod 640 /etc/pgbackrest/pgbackrest.conf
PG_CONF_D="/etc/postgresql/$PG_VER/main/conf.d"
install -d "$PG_CONF_D"
ARCHIVE_CONF="$PG_CONF_D/stats-collector-archive.conf"
NEW_ARCHIVE="archive_mode = on
archive_command = 'pgbackrest --stanza=$STANZA archive-push %p'
wal_level = replica
max_wal_senders = 3"
if [ "$(cat "$ARCHIVE_CONF" 2>/dev/null)" != "$NEW_ARCHIVE" ]; then
  echo "$NEW_ARCHIVE" > "$ARCHIVE_CONF"
  systemctl restart postgresql
  for _ in $(seq 1 30); do runuser -u postgres -- pg_isready -q && break; sleep 1; done
fi
pgb() { # run pgBackRest quietly, but show its output when it fails
  local out
  out="$(runuser -u postgres -- pgbackrest --stanza="$STANZA" "$@" 2>&1)" || { echo "$out" >&2; die "pgbackrest $* failed"; }
}
pgb stanza-create
pgb check
ok "WAL archiving and stanza $STANZA"

# ----------------------------------------------------------------------------------------------------------
step "Installing the application"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
if [ -n "$TARBALL" ]; then
  cp "$TARBALL" "$WORK/"
  PKG="$WORK/$(basename "$TARBALL")"
elif [ -n "$SOURCE" ]; then
  VERSION="$(cat "$SOURCE/VERSION").dev$(date +%Y%m%d%H%M%S)"
  [ -f "$SOURCE/frontend/dist/index.html" ] || (cd "$SOURCE/frontend" && npm ci --no-audit --no-fund --silent && npm run build --silent)
  PKG="$(bash "$SOURCE/scripts/package.sh" "$VERSION" "$CHANNEL" "$(git -C "$SOURCE" rev-parse HEAD 2>/dev/null || echo local)" | tail -1)"
else
  API="https://api.github.com/repos/$REPO/releases?per_page=30"
  if [ "$CHANNEL" = production ]; then FILTER='map(select(.prerelease==false and .draft==false))'
  else FILTER='map(select(.draft==false))'; fi
  ASSET="$(curl -fsSL "$API" | jq -r "$FILTER | map(.assets[] | select(.name|endswith(\".tar.gz\")) | .browser_download_url) | .[0] // empty")"
  if [ -z "$ASSET" ]; then
    warn "No $CHANNEL release published yet; building from the $([ "$CHANNEL" = test ] && echo develop || echo main) branch."
    apt-get install -y -qq nodejs npm >/dev/null
    BRANCH="$([ "$CHANNEL" = test ] && echo develop || echo main)"
    git clone -q --depth 1 --branch "$BRANCH" "https://github.com/$REPO.git" "$WORK/src"
    VERSION="$(cat "$WORK/src/VERSION").dev$(date +%Y%m%d%H%M%S)"
    PKG="$(bash "$WORK/src/scripts/package.sh" "$VERSION" "$CHANNEL" "$(git -C "$WORK/src" rev-parse HEAD)" | tail -1)"
  else
    curl -fsSL -o "$WORK/release.tar.gz" "$ASSET"
    curl -fsSL -o "$WORK/release.tar.gz.sha256" "$ASSET.sha256"
    (cd "$WORK" && echo "$(cut -d' ' -f1 release.tar.gz.sha256)  release.tar.gz" | sha256sum -c --quiet) \
      || die "Checksum of the downloaded release does not match."
    PKG="$WORK/release.tar.gz"
    ok "Downloaded $(basename "$ASSET")"
  fi
fi

mkdir -p "$WORK/x"; tar -xzf "$PKG" -C "$WORK/x"
TOP="$(find "$WORK/x" -mindepth 1 -maxdepth 1 -type d | head -1)"
VERSION="$(cat "$TOP/VERSION")"
TARGET="$INSTALL_DIR/releases/$VERSION"
if [ "$(readlink -f "$INSTALL_DIR/current" 2>/dev/null)" = "$TARGET" ]; then
  ok "Version $VERSION is already installed"
else
  rm -rf "$TARGET"; mv "$TOP" "$TARGET"
  python3 -m venv "$TARGET/venv"
  "$TARGET/venv/bin/pip" install --quiet --no-cache-dir --upgrade pip
  "$TARGET/venv/bin/pip" install --quiet --no-cache-dir -e "$TARGET/backend"
  chown -R root:root "$TARGET"; chmod -R go-w "$TARGET"
  ok "Installed version $VERSION"
fi

step "Database migrations"
runuser -u "$APP_USER" -- env SC_CONFIG_FILE="$CONF" "$TARGET/venv/bin/stats-collector" migrate
ln -sfn "$TARGET" "$INSTALL_DIR/current.new" && mv -T "$INSTALL_DIR/current.new" "$INSTALL_DIR/current"
cat > /usr/local/bin/stats-collector <<'EOF'
#!/bin/sh
# Wrapper: runs the CLI as the application user (root-only commands like "ops" run as root).
case "$1" in ops|backup|restore) exec env SC_CONFIG_FILE=/etc/stats-collector/config.env /opt/stats-collector/current/venv/bin/stats-collector "$@" ;; esac
exec runuser -u statscollector -- env SC_CONFIG_FILE=/etc/stats-collector/config.env /opt/stats-collector/current/venv/bin/stats-collector "$@"
EOF
chmod 755 /usr/local/bin/stats-collector
ok "Schema up to date"

# ----------------------------------------------------------------------------------------------------------
step "System services"
install -m 644 "$TARGET"/deploy/systemd/*.service "$TARGET"/deploy/systemd/*.path "$TARGET"/deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now stats-collector-ops.path stats-collector-backup.timer >/dev/null 2>&1
systemctl enable stats-collector-web >/dev/null 2>&1
systemctl restart stats-collector-web
for _ in $(seq 1 40); do curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null || { journalctl -u stats-collector-web -n 40 --no-pager; die "The web service did not start."; }
ok "stats-collector-web on port $PORT, ops runner and hourly backup timer"

if [ "$FIREWALL" = 1 ]; then
  step "Firewall (nftables)"
  cat > /etc/nftables.d-stats-collector.nft <<EOF
table inet stats_collector {
  chain input {
    type filter hook input priority 0; policy accept;
    tcp dport { $PORT, 8081 } ip saddr { ${PROXY_IPS//,/, } } accept
    tcp dport { $PORT, 8081 } iif lo accept
    tcp dport { $PORT, 8081 } drop
  }
}
EOF
  nft -f /etc/nftables.d-stats-collector.nft
  grep -q nftables.d-stats-collector /etc/nftables.conf || echo 'include "/etc/nftables.d-stats-collector.nft"' >> /etc/nftables.conf
  systemctl enable nftables >/dev/null 2>&1
  ok "Ports $PORT and 8081 only reachable from $PROXY_IPS"
fi

step "First backup"
if /usr/local/bin/stats-collector backup full --if-none >/tmp/sc-first-backup.log 2>&1; then
  ok "Full backup made (kept locally until you add a remote location)"
else
  warn "The first backup failed; see /tmp/sc-first-backup.log. The hourly timer will try again."
fi

step "Cleaning up old releases"
CUR="$(readlink -f "$INSTALL_DIR/current")"
# keep the current release and the two newest others (for rollback); remove everything older or half-installed
mapfile -t OLD < <(find "$INSTALL_DIR/releases" -mindepth 1 -maxdepth 1 -type d ! -path "$CUR" -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)
for i in "${!OLD[@]}"; do
  d="${OLD[$i]}"
  if [ "$i" -ge 2 ] || [ ! -x "$d/venv/bin/stats-collector" ] || [[ "$(basename "$d")" == .* ]]; then rm -rf "$d"; fi
done
ok "$(find "$INSTALL_DIR/releases" -mindepth 1 -maxdepth 1 -type d | wc -l) release(s) on disk"

# ----------------------------------------------------------------------------------------------------------
echo
echo "${c_b}Stats Collector $VERSION is running.${c_0}"
echo "  Local:       http://127.0.0.1:$PORT"
echo "  Public URL:  $PUBLIC_URL  (configure the reverse proxy: docs/manual/en/reverse-proxy.md)"
echo "  Channel:     $CHANNEL"
LINK="$(/usr/local/bin/stats-collector setup-link 2>/dev/null || true)"
if [ -n "$LINK" ]; then
  echo
  echo "${c_b}Create the first administrator (link valid for 24 hours):${c_0}"
  echo "  $LINK"
else
  echo "  An administrator account already exists."
fi
