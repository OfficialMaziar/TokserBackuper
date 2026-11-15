#!/usr/bin/env bash
#
# Tokser Backup Manager — installer for Debian / Ubuntu
#
# Usage:
#   sudo ./scripts/install.sh [options]
#
# Interactive installer. When run in a terminal it asks which ports to use and
# skips a busy default automatically, so it can be installed alongside existing
# sites on the same server.
#
# Usage:
#   sudo ./scripts/install.sh [options]
#
# Options:
#   --domain DOMAIN      Public hostname for the Nginx vhost (default: _)
#   --port PORT          Internal application port (default: 8000, auto if busy)
#   --http-port PORT     Public HTTP port for Nginx (default: 80, auto if busy)
#   --https-port PORT    Public HTTPS port for Nginx (default: 443)
#   --no-nginx           Skip Nginx configuration (app is reachable on --port)
#   --no-systemd         Skip systemd unit installation (run manually)
#   --self-signed        Generate a self-signed TLS certificate
#   --non-interactive    Do not prompt (uses defaults / flags only)
#   -h, --help           Show this help
#
set -Eeuo pipefail

APP_NAME="Tokser Backup Manager"
APP_USER="TBM"
APP_DIR="/opt/tokser-backup-manager"
DATA_DIR="${APP_DIR}/data"
LOG_DIR="${APP_DIR}/logs"
BACKUP_DIR="/var/backups/tokser"
VENV="${APP_DIR}/.venv"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DOMAIN="_"
APP_PORT="8000"
APP_PORT_SET=0        # 1 when --port was given explicitly
PUBLIC_HTTP_PORT=80
PUBLIC_HTTPS_PORT=443
HTTP_PORT_SET=0       # 1 when --http-port was given explicitly
DO_NGINX=1
DO_SYSTEMD=1
SELF_SIGNED=0
NON_INTERACTIVE=0

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_INFO=$'\033[36m'; C_OK=$'\033[32m'
  C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_BOLD=$'\033[1m'
else
  C_RESET=""; C_INFO=""; C_OK=""; C_WARN=""; C_ERR=""; C_BOLD=""
fi

step()  { printf "\n%s==> %s%s\n" "${C_BOLD}${C_INFO}" "$*" "${C_RESET}"; }
ok()    { printf "%s  ✔ %s%s\n" "${C_OK}" "$*" "${C_RESET}"; }
warn()  { printf "%s  ! %s%s\n" "${C_WARN}" "$*" "${C_RESET}"; }
err()   { printf "%s  ✘ %s%s\n" "${C_ERR}" "$*" "${C_RESET}" >&2; }
die()   { err "$*"; exit 1; }

trap 'err "Installation failed at line ${LINENO}."' ERR

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)          DOMAIN="${2:?--domain requires a value}"; shift 2 ;;
    --port)            APP_PORT="${2:?--port requires a value}"; APP_PORT_SET=1; shift 2 ;;
    --http-port)       PUBLIC_HTTP_PORT="${2:?--http-port requires a value}"; HTTP_PORT_SET=1; shift 2 ;;
    --https-port)      PUBLIC_HTTPS_PORT="${2:?--https-port requires a value}"; shift 2 ;;
    --no-nginx)        DO_NGINX=0; shift ;;
    --no-systemd)      DO_SYSTEMD=0; shift ;;
    --self-signed)     SELF_SIGNED=1; shift ;;
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    -h|--help)         sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)                 die "Unknown option: $1 (use --help)" ;;
  esac
done

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
step "Checking system"

[[ "${EUID}" -eq 0 ]] || die "This installer must run as root (use sudo)."

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  ok "Detected ${PRETTY_NAME:-unknown OS}"
  case "${ID:-}" in
    debian|ubuntu)
      case "${VERSION_ID:-0}" in
        12|13|22.04|24.04|24.10|25.04) ok "OS version supported" ;;
        *) warn "OS version ${VERSION_ID} is untested (expected Debian 12+/Ubuntu 22.04+)" ;;
      esac
      ;;
    *)
      warn "Distribution '${ID:-unknown}' is not officially supported. Continuing anyway."
      ;;
  esac
else
  warn "Cannot read /etc/os-release; assuming a Debian-like system."
fi

command -v systemctl >/dev/null || die "systemd is required."
command -v apt-get >/dev/null || die "apt-get not found — this installer targets Debian/Ubuntu."

# Python 3.12+
if command -v python3 >/dev/null; then
  PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  PY_MAJOR="${PY_VER%%.*}"; PY_MINOR="${PY_VER##*.}"
  if (( PY_MAJOR > 3 || (PY_MAJOR == 3 && PY_MINOR >= 12) )); then
    ok "Python ${PY_VER} found"
  else
    warn "Python ${PY_VER} found; 3.12+ is required"
  fi
else
  warn "python3 not found — it will be installed"
fi

# ---------------------------------------------------------------------------
# Port selection
#
# Port 8000 is only the internal port the app binds to (127.0.0.1). Nginx is
# what faces the internet on 80/443 — that is the port that clashes when one
# server already hosts another site. Both are therefore selects at install
# time, and a busy default is skipped automatically.
# ---------------------------------------------------------------------------
port_in_use() {
  local port="$1"
  ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}$"
}

free_port_near() {
  local start="$1" candidate
  for offset in $(seq 0 50); do
    candidate=$(( start + offset ))
    (( candidate > 65535 )) && break
    if ! port_in_use "${candidate}"; then
      printf '%s' "${candidate}"
      return 0
    fi
  done
  return 1
}

valid_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && (( $1 >= 1 && $1 <= 65535 ))
}

# --- internal application port ---------------------------------------------
SUGGESTED_APP_PORT=""
if port_in_use "${APP_PORT}"; then
  if SUGGESTED_APP_PORT="$(free_port_near "${APP_PORT}")"; then
    if [[ "${APP_PORT_SET}" -eq 1 ]]; then
      die "Port ${APP_PORT} is already in use. Try --port ${SUGGESTED_APP_PORT}."
    fi
    warn "Port ${APP_PORT} is in use; ${SUGGESTED_APP_PORT} is free"
    APP_PORT="${SUGGESTED_APP_PORT}"
  else
    die "Port ${APP_PORT} is in use and no nearby port is free."
  fi
fi

if [[ "${NON_INTERACTIVE}" -eq 0 && -t 0 ]]; then
  printf "\n  Internal application port (bound to 127.0.0.1 only) [%s]: " "${APP_PORT}"
  read -r input_port
  input_port="$(printf '%s' "${input_port}" | tr -d '[:space:]')"
  if [[ -n "${input_port}" ]]; then
    if ! valid_port "${input_port}"; then
      die "'${input_port}' is not a valid port (1-65535)."
    fi
    if port_in_use "${input_port}"; then
      die "Port ${input_port} is already in use."
    fi
    APP_PORT="${input_port}"
  fi
fi
ok "Application port: ${APP_PORT}"

# --- public HTTP/HTTPS ports (Nginx) ---------------------------------------
if [[ "${DO_NGINX}" -eq 1 ]]; then
  if [[ "${HTTP_PORT_SET}" -eq 1 ]]; then
    if ! valid_port "${PUBLIC_HTTP_PORT}"; then
      die "'${PUBLIC_HTTP_PORT}' is not a valid HTTP port."
    fi
    if port_in_use "${PUBLIC_HTTP_PORT}"; then
      die "Port ${PUBLIC_HTTP_PORT} is already in use."
    fi
    ok "Public HTTP port: ${PUBLIC_HTTP_PORT} (from --http-port)"
  elif port_in_use "${PUBLIC_HTTP_PORT}"; then
    if existing_conf="$(ls /etc/nginx/sites-enabled/ 2>/dev/null | grep -v 'tokser-backup-manager' | head -n 1)"; then
      warn "Port ${PUBLIC_HTTP_PORT} is already served by Nginx (site: ${existing_conf})"
    else
      warn "Port ${PUBLIC_HTTP_PORT} is already in use by another service"
    fi
    if ALT_HTTP="$(free_port_near 8080)"; then
      warn "Publishing on ${ALT_HTTP} instead; other sites on 80 are untouched"

      if [[ "${NON_INTERACTIVE}" -eq 0 && -t 0 ]]; then
        printf "\n  Public HTTP port for Tokser Backup Manager [%s]: " "${ALT_HTTP}"
        read -r input_http
        input_http="$(printf '%s' "${input_http}" | tr -d '[:space:]')"
        if [[ -n "${input_http}" ]]; then
          if ! valid_port "${input_http}"; then
            die "'${input_http}' is not a valid port (1-65535)."
          fi
          if port_in_use "${input_http}"; then
            die "Port ${input_http} is already in use."
          fi
          ALT_HTTP="${input_http}"
        fi
      fi
      PUBLIC_HTTP_PORT="${ALT_HTTP}"
    else
      die "Port 80 is in use and no nearby alternative is free."
    fi
  elif [[ "${NON_INTERACTIVE}" -eq 0 && -t 0 ]]; then
    printf "\n  Public HTTP port for the panel [%s]: " "${PUBLIC_HTTP_PORT}"
    read -r input_http
    input_http="$(printf '%s' "${input_http}" | tr -d '[:space:]')"
    if [[ -n "${input_http}" ]]; then
      if ! valid_port "${input_http}"; then
        die "'${input_http}' is not a valid port (1-65535)."
      fi
      if port_in_use "${input_http}"; then
        die "Port ${input_http} is already in use."
      fi
      PUBLIC_HTTP_PORT="${input_http}"
    fi
  fi
  ok "Public HTTP port: ${PUBLIC_HTTP_PORT}"

  # HTTPS port: only meaningful when a certificate exists.
  if [[ "${SELF_SIGNED}" -eq 1 ]] && port_in_use "${PUBLIC_HTTPS_PORT}"; then
    if ALT_HTTPS="$(free_port_near 8443)"; then
      warn "Port ${PUBLIC_HTTPS_PORT} is in use; publishing HTTPS on ${ALT_HTTPS}"
      PUBLIC_HTTPS_PORT="${ALT_HTTPS}"
    else
      die "Port ${PUBLIC_HTTPS_PORT} is in use and no alternative is free."
    fi
  fi
fi
ok "Port ${APP_PORT} is free"

# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------
step "Installing system packages"

export DEBIAN_FRONTEND=noninteractive

# A previous interrupted run leaves dpkg half-configured; every later install
# then fails with "dpkg returned an error code (1)". Repair first.
if ! dpkg --audit >/dev/null 2>&1 || [[ -n "$(dpkg --audit 2>/dev/null)" ]]; then
  warn "dpkg reports a broken package state — attempting repair"
  dpkg --configure -a >/dev/null 2>&1 || true
  apt-get install -f -y >/dev/null 2>&1 || true
  ok "dpkg repair attempted"
fi

# Drop stale locks left by an interrupted apt run.
for lockfile in /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock \
                /var/cache/apt/archives/lock /var/lib/apt/lists/lock; do
  if [[ -f "${lockfile}" ]] && fuser "${lockfile}" >/dev/null 2>&1; then
    warn "Another apt/dpkg process holds ${lockfile}"
    die "Wait for it to finish (or reboot) and re-run the installer."
  fi
done

APT_LOG="$(mktemp /tmp/tbm-apt.XXXXXX.log)"
if ! apt-get update -qq 2>"${APT_LOG}"; then
  warn "apt-get update reported errors (continuing with the existing lists)"
  tail -n 5 "${APT_LOG}" | sed 's/^/    /' >&2
fi

PACKAGES=(
  python3 python3-venv python3-dev python3-pip
  build-essential pkg-config
  tar gzip zip unzip zstd
  ca-certificates curl openssl
  rsync
  acl
)

ok "Installing packages: ${PACKAGES[*]}"
if ! apt-get install -y -qq "${PACKAGES[@]}" >"${APT_LOG}" 2>&1; then
  err "Package installation failed. Last lines from apt:"
  tail -n 25 "${APT_LOG}" | sed 's/^/    /' >&2
  err "Full log: ${APT_LOG}"

  # Retry once after a repair — the common cause is a half-configured package
  # left behind by an interrupted apt run.
  warn "Retrying after 'dpkg --configure -a' and 'apt-get -f install'"
  dpkg --configure -a >>"${APT_LOG}" 2>&1 || true
  apt-get install -f -y >>"${APT_LOG}" 2>&1 || true
  if apt-get install -y -qq "${PACKAGES[@]}" >>"${APT_LOG}" 2>&1; then
    ok "Base packages installed on retry"
  else
    err "Still failing. Last lines:"
    tail -n 25 "${APT_LOG}" | sed 's/^/    /' >&2
    die "Could not install required packages. Fix the apt error above and re-run.
     Common causes: no network, a broken mirror in /etc/apt/sources.list,
     or a half-installed package named in the output above."
  fi
else
  ok "Base packages installed"
fi
rm -f "${APT_LOG}"

# Database client tools are optional but enable DB backups.
for tool in mysqldump pg_dump; do
  if command -v "$tool" >/dev/null; then
    ok "${tool} available"
  else
    warn "${tool} not installed — database backups of that type will report a clear error"
  fi
done

# ---------------------------------------------------------------------------
# Service user
# ---------------------------------------------------------------------------
step "Creating service user"

if id -u "${APP_USER}" >/dev/null 2>&1; then
  ok "User '${APP_USER}' already exists"
else
  # A system account with no login shell and no password. It runs the service
  # and is never a member of sudo/admin.
  useradd --system --create-home --home-dir "${APP_DIR}" \
          --shell /usr/sbin/nologin "${APP_USER}"
  passwd -l "${APP_USER}" >/dev/null 2>&1 || true
  ok "Created system user '${APP_USER}' (no login shell, no password)"
fi

# The service must never run as root. Verify the account really is unprivileged.
if id -nG "${APP_USER}" 2>/dev/null | tr ' ' '\n' | grep -qxE "sudo|wheel|admin"; then
  warn "User '${APP_USER}' is in an administrative group — removing it"
  for grp in sudo wheel admin; do
    if id -nG "${APP_USER}" 2>/dev/null | tr ' ' '\n' | grep -qx "${grp}"; then
      gpasswd -d "${APP_USER}" "${grp}" >/dev/null 2>&1 || true
    fi
  done
fi

# ---------------------------------------------------------------------------
# Application files
# ---------------------------------------------------------------------------
step "Installing application files"

# Preserve user data on re-install / upgrade.
if [[ -d "${APP_DIR}" ]]; then
  warn "Existing installation found at ${APP_DIR}"
  if [[ "${NON_INTERACTIVE}" -eq 0 ]]; then
    read -r -p "  Upgrade in place, keeping data, config and .env? [Y/n] " reply
    case "${reply:-Y}" in
      [Nn]*) die "Aborted by user." ;;
    esac
  fi
  mkdir -p "${APP_DIR}.bak"
  cp -a "${APP_DIR}/.env" "${APP_DIR}.bak/.env" 2>/dev/null || true
  cp -a "${APP_DIR}/config.yaml" "${APP_DIR}.bak/config.yaml" 2>/dev/null || true
  ok "Backed up existing .env / config.yaml"
fi

mkdir -p "${APP_DIR}" "${DATA_DIR}" "${LOG_DIR}" "${BACKUP_DIR}"

# Copy source, excluding local dev artefacts and user data.
rsync -a --delete \
  --exclude '.git' --exclude '.venv' --exclude 'data' --exclude 'logs' \
  --exclude 'backups' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude '.env' --exclude 'config.yaml' \
  "${SRC_DIR}/" "${APP_DIR}/"
ok "Application files copied to ${APP_DIR}"

chmod 750 "${DATA_DIR}" "${LOG_DIR}"
chmod 750 "${BACKUP_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}" "${BACKUP_DIR}"

# ---------------------------------------------------------------------------
# Virtual environment
# ---------------------------------------------------------------------------
step "Creating Python virtual environment"

if [[ ! -d "${VENV}" ]]; then
  python3 -m venv "${VENV}"
fi
"${VENV}/bin/pip" install --quiet --upgrade pip setuptools wheel
"${VENV}/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"
ok "Python dependencies installed"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
step "Preparing configuration"

if [[ ! -f "${APP_DIR}/.env" ]]; then
  SECRET_KEY="$("${VENV}/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  ENCRYPT_KEY="$("${VENV}/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  cat > "${APP_DIR}/.env" <<EOF
TBM_ENV=production
TBM_DEBUG=false
TBM_HOST=127.0.0.1
TBM_PORT=${APP_PORT}
TBM_DATA_DIR=${DATA_DIR}
TBM_BACKUP_DIR=${BACKUP_DIR}
TBM_LOG_DIR=${LOG_DIR}
TBM_SECRET_KEY=${SECRET_KEY}
TBM_ENCRYPTION_KEY=${ENCRYPT_KEY}
TBM_SESSION_TTL=12
TBM_SECURE_COOKIE=$([[ "${SELF_SIGNED}" -eq 1 || "${DOMAIN}" != "_" ]] && echo true || echo false)
TBM_SCHEDULER=true
TBM_TIMEZONE=UTC
EOF
  chmod 600 "${APP_DIR}/.env"
  chown "${APP_USER}:${APP_USER}" "${APP_DIR}/.env"
  ok "Generated .env with random secrets"
else
  if grep -qE '^TBM_PORT=' "${APP_DIR}/.env"; then
    sed -i "s|^TBM_PORT=.*|TBM_PORT=${APP_PORT}|" "${APP_DIR}/.env"
  else
    echo "TBM_PORT=${APP_PORT}" >> "${APP_DIR}/.env"
  fi
  ok "Existing .env preserved (port set to ${APP_PORT})"
fi

if [[ ! -f "${APP_DIR}/config.yaml" ]]; then
  cp "${APP_DIR}/config.example.yaml" "${APP_DIR}/config.yaml"
  chown "${APP_USER}:${APP_USER}" "${APP_DIR}/config.yaml"
  ok "Created config.yaml from example"
fi

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
step "Initialising database"

# Verify the configuration parses before running the full bootstrap so a bad
# value produces a clear message instead of a Python traceback.
if ! CONFIG_CHECK="$(runuser -u "${APP_USER}" -- bash -lc "
  cd '${APP_DIR}'
  set -a; . '${APP_DIR}/.env'; set +a
  '${VENV}/bin/python' -c 'from app.core.config import settings; print(settings.database_url)'
" 2>&1)"; then
  err "Configuration could not be loaded:"
  printf '%s\n' "${CONFIG_CHECK}" | tail -n 15 >&2
  die "Check ${APP_DIR}/.env and ${APP_DIR}/config.yaml, then re-run the installer."
fi
ok "Configuration loaded (database: ${CONFIG_CHECK})"

if ! BOOTSTRAP_OUT="$(runuser -u "${APP_USER}" -- bash -lc "
  cd '${APP_DIR}'
  set -a; . '${APP_DIR}/.env'; set +a
  '${VENV}/bin/python' -c 'from app.main import bootstrap; bootstrap(); print(\"database ready\")'
" 2>&1)"; then
  err "Database initialisation failed:"
  printf '%s\n' "${BOOTSTRAP_OUT}" | tail -n 25 >&2
  die "Fix the error above and re-run the installer."
fi
ok "Database schema ready"

# ---------------------------------------------------------------------------
# Administrator account
# ---------------------------------------------------------------------------
step "Administrator account"

ADMIN_COUNT="$(runuser -u "${APP_USER}" -- bash -lc "
  cd '${APP_DIR}'
  set -a; . '${APP_DIR}/.env'; set +a
  '${VENV}/bin/python' -c '
from app.core.database import SessionLocal
from app.services.auth import is_setup_required
db = SessionLocal(); print(1 if is_setup_required(db) else 0); db.close()
'
")"

if [[ "${ADMIN_COUNT}" == "1" ]]; then
  if [[ "${NON_INTERACTIVE}" -eq 1 ]]; then
    warn "No administrator exists. Complete setup at https://<host>/setup"
  else
    cat <<'EOF'

  No administrator account exists yet.
  For security the password is never generated or printed automatically.
  You can either:
    1) create it now (recommended), or
    2) finish at the web setup page after the service starts.

EOF
    read -r -p "  Create the administrator now? [Y/n] " create_now
    case "${create_now:-Y}" in
      [Nn]*) warn "Skipped — complete setup at /setup" ;;
      *)
        read -r -p "  Admin username [admin]: " ADMIN_USER
        ADMIN_USER="${ADMIN_USER:-admin}"
        while true; do
          read -r -s -p "  Admin password (min 10 chars, letters + digits): " ADMIN_PASS; echo
          read -r -s -p "  Confirm password: " ADMIN_PASS2; echo
          [[ "${ADMIN_PASS}" == "${ADMIN_PASS2}" ]] || { warn "Passwords do not match"; continue; }
          [[ ${#ADMIN_PASS} -ge 10 ]] || { warn "Too short"; continue; }
          [[ "${ADMIN_PASS}" =~ [A-Za-z] && "${ADMIN_PASS}" =~ [0-9] ]] || { warn "Must contain letters and digits"; continue; }
          break
        done
        ADMIN_USER="${ADMIN_USER}" ADMIN_PASS="${ADMIN_PASS}" \
        runuser -u "${APP_USER}" --preserve-environment -- bash -lc "
          cd '${APP_DIR}'
          set -a; . '${APP_DIR}/.env'; set +a
          '${VENV}/bin/python' - <<'PY'
import os
from app.core.database import SessionLocal
from app.services.auth import create_user, ensure_roles
db = SessionLocal()
ensure_roles(db)
create_user(db, username=os.environ['ADMIN_USER'],
            password=os.environ['ADMIN_PASS'], role='admin',
            full_name='Administrator')
print('administrator created')
db.close()
PY
        "
        ok "Administrator '${ADMIN_USER}' created"
        ;;
    esac
  fi
else
  ok "Administrator account already exists"
fi

# ---------------------------------------------------------------------------
# Command line tool
# ---------------------------------------------------------------------------
step "Installing the 'tbm' command"

install -m 0755 "${APP_DIR}/scripts/tbm" /usr/local/bin/tbm
ok "Installed /usr/local/bin/tbm"

# ---------------------------------------------------------------------------
# systemd
# ---------------------------------------------------------------------------
if [[ "${DO_SYSTEMD}" -eq 1 ]]; then
  step "Configuring systemd service"

  sed -e "s|^WorkingDirectory=.*|WorkingDirectory=${APP_DIR}|" \
      -e "s|^EnvironmentFile=.*|EnvironmentFile=-${APP_DIR}/.env|" \
      -e "s|/opt/tokser-backup-manager|${APP_DIR}|g" \
      -e "s|/var/backups/tokser|${BACKUP_DIR}|g" \
      -e "s|--port 8000|--port ${APP_PORT}|" \
      "${APP_DIR}/systemd/TBM.service" \
      > /etc/systemd/system/TBM.service
  chmod 644 /etc/systemd/system/TBM.service

  systemctl daemon-reload
  systemctl enable TBM.service >/dev/null 2>&1
  systemctl restart TBM.service
  ok "Service enabled and started"
else
  warn "systemd unit not installed (--no-systemd)"
fi

# ---------------------------------------------------------------------------
# Nginx
# ---------------------------------------------------------------------------
if [[ "${DO_NGINX}" -eq 1 ]]; then
  step "Configuring Nginx"

  if ! command -v nginx >/dev/null; then
    apt-get install -y -qq nginx >/dev/null
    ok "Nginx installed"
  else
    ok "Nginx already installed"
  fi

  CERT_DIR="/etc/ssl/tokser"
  CERT_FILE=""; KEY_FILE=""

  if [[ "${SELF_SIGNED}" -eq 1 ]]; then
    mkdir -p "${CERT_DIR}"
    if [[ ! -f "${CERT_DIR}/tbm.crt" ]]; then
      openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
        -keyout "${CERT_DIR}/tbm.key" -out "${CERT_DIR}/tbm.crt" \
        -subj "/CN=${DOMAIN/_/localhost}/O=TokserTeam" >/dev/null 2>&1
      chmod 600 "${CERT_DIR}/tbm.key"
      ok "Self-signed certificate generated"
    fi
    CERT_FILE="${CERT_DIR}/tbm.crt"
    KEY_FILE="${CERT_DIR}/tbm.key"
  elif [[ "${DOMAIN}" != "_" ]]; then
    if command -v certbot >/dev/null; then
      ok "certbot available — run 'certbot --nginx -d ${DOMAIN}' after install for a trusted certificate"
    else
      warn "No TLS certificate yet. Install certbot and run: certbot --nginx -d ${DOMAIN}"
    fi
  fi

  NGINX_CONF="/etc/nginx/sites-available/tokser-backup-manager"
  {
    if [[ -n "${CERT_FILE}" ]]; then
      echo "server {"
      echo "    listen ${PUBLIC_HTTP_PORT};"
      echo "    server_name ${DOMAIN};"
      echo "    return 301 https://\$host\$request_uri;"
      echo "}"
      echo
    fi
    echo "server {"
    if [[ -n "${CERT_FILE}" ]]; then
      echo "    listen ${PUBLIC_HTTPS_PORT} ssl http2;"
      echo "    ssl_certificate ${CERT_FILE};"
      echo "    ssl_certificate_key ${KEY_FILE};"
      echo "    ssl_protocols TLSv1.2 TLSv1.3;"
      echo "    ssl_prefer_server_ciphers on;"
    else
      echo "    listen ${PUBLIC_HTTP_PORT};"
    fi
    echo "    server_name ${DOMAIN};"
    echo
    echo "    client_max_body_size 100M;"
    echo
    echo "    add_header X-Content-Type-Options nosniff always;"
    echo "    add_header X-Frame-Options DENY always;"
    echo "    add_header Referrer-Policy strict-origin-when-cross-origin always;"
    echo
    echo "    location /static/ {"
    echo "        alias ${APP_DIR}/app/static/;"
    echo "        expires 7d;"
    echo "        access_log off;"
    echo "    }"
    echo
    echo "    location / {"
    echo "        proxy_pass http://127.0.0.1:${APP_PORT};"
    echo "        proxy_http_version 1.1;"
    echo "        proxy_set_header Host \$host;"
    echo "        proxy_set_header X-Real-IP \$remote_addr;"
    echo "        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;"
    echo "        proxy_set_header X-Forwarded-Proto \$scheme;"
    echo "        proxy_read_timeout 300s;"
    echo "        proxy_send_timeout 300s;"
    echo "        proxy_request_buffering off;"
    echo "    }"
    echo "}"
  } > "${NGINX_CONF}"

  ln -sfn "${NGINX_CONF}" /etc/nginx/sites-enabled/tokser-backup-manager

  # The stock Debian/Ubuntu "default" site would answer on port 80 and shadow
  # this one. Remove it only when it is still the untouched stock file — an
  # existing site the administrator configured is never deleted.
  DEFAULT_SITE="/etc/nginx/sites-enabled/default"
  if [[ -L "${DEFAULT_SITE}" || -f "${DEFAULT_SITE}" ]]; then
    if grep -qs "default_server" "${DEFAULT_SITE}" \
       && grep -qs "/var/www/html" "${DEFAULT_SITE}" \
       && ! grep -qs "proxy_pass" "${DEFAULT_SITE}"; then
      rm -f "${DEFAULT_SITE}"
      ok "Removed the stock Nginx default site"
    else
      warn "Left ${DEFAULT_SITE} in place — it is not the stock welcome page"
      warn "If it captures port ${PUBLIC_HTTP_PORT}, disable it manually"
    fi
  fi

  if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
    ok "Nginx configured and reloaded"
  else
    err "Nginx configuration test failed:"
    nginx -t || true
    die "Fix the Nginx configuration and re-run."
  fi
else
  warn "Nginx not configured (--no-nginx)"
fi

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
step "Verifying installation"

HEALTH_OK=0
for attempt in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${APP_PORT}/api/v1/health" >/dev/null 2>&1; then
    HEALTH_OK=1
    break
  fi
  sleep 1
done

if [[ "${HEALTH_OK}" -eq 1 ]]; then
  ok "Application responds on port ${APP_PORT}"
  if [[ "${DO_SYSTEMD}" -eq 1 ]]; then
    systemctl is-active --quiet TBM.service \
      && ok "Service is active" \
      || warn "Service is not active — check: journalctl -u tokser-backup-manager -n 50"
  fi
else
  err "Application did not respond within 30s."
  if [[ "${DO_SYSTEMD}" -eq 1 ]]; then
    journalctl -u TBM -n 30 --no-pager || true
  fi
  die "Health check failed. Review the logs above."
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
HOST_DISPLAY="${DOMAIN}"
[[ "${HOST_DISPLAY}" == "_" ]] && HOST_DISPLAY="$(hostname -I 2>/dev/null | awk '{print $1}')"
[[ -z "${HOST_DISPLAY}" ]] && HOST_DISPLAY="<server-ip>"

# Build the real panel URL: scheme depends on whether TLS was configured,
# and the port is omitted only when it is the scheme's default.
if [[ "${DO_NGINX}" -eq 0 ]]; then
  PANEL_URL="http://${HOST_DISPLAY}:${APP_PORT}/"
elif [[ -n "${CERT_FILE}" ]]; then
  if [[ "${PUBLIC_HTTPS_PORT}" -eq 443 ]]; then
    PANEL_URL="https://${HOST_DISPLAY}/"
  else
    PANEL_URL="https://${HOST_DISPLAY}:${PUBLIC_HTTPS_PORT}/"
  fi
else
  if [[ "${PUBLIC_HTTP_PORT}" -eq 80 ]]; then
    PANEL_URL="http://${HOST_DISPLAY}/"
  else
    PANEL_URL="http://${HOST_DISPLAY}:${PUBLIC_HTTP_PORT}/"
  fi
fi

# ---------------------------------------------------------------------------
# Read access to protected directories
#
# The service runs as an unprivileged account and cannot read /root (mode
# 0700). A POSIX ACL grants that one account read + traverse permission
# without making the service root.
# ---------------------------------------------------------------------------
if command -v setfacl >/dev/null 2>&1; then
  step "Backup access to protected directories"

  GRANT_ROOT=0
  if [[ "${NON_INTERACTIVE}" -eq 0 && -t 0 ]]; then
    cat <<EOF

  The service runs as '${APP_USER}' (not root). To back up /root it needs
  read-only access, granted with a POSIX ACL. Write access is never granted.

EOF
    read -r -p "  Grant read access to /root? [y/N] " grant_root
    [[ "${grant_root}" =~ ^[Yy]$ ]] && GRANT_ROOT=1
  fi

  if [[ "${GRANT_ROOT}" -eq 1 ]]; then
    if setfacl -R -m "u:${APP_USER}:rX" /root 2>/dev/null; then
      setfacl -m "u:${APP_USER}:x" / 2>/dev/null || true
      ok "Granted read access to /root"
    else
      warn "Could not set ACL on /root — run later: sudo tbm access grant /root"
    fi
  else
    ok "Skipped — grant later with: sudo tbm access grant /root"
  fi

  # Common application directories people expect to back up.
  for candidate in /var/www /etc/nginx /etc/apache2 /var/lib/mysql; do
    [[ -d "${candidate}" ]] || continue
    if runuser -u "${APP_USER}" -- test -r "${candidate}" 2>/dev/null; then
      ok "${candidate} readable"
    else
      warn "${candidate} not readable — sudo tbm access grant ${candidate}"
    fi
  done
else
  warn "setfacl not available — install 'acl' to grant access to /root"
fi

cat <<EOF

${C_BOLD}${C_OK}${APP_NAME} installed successfully${C_RESET}

  Panel:        ${C_BOLD}${PANEL_URL}${C_RESET}
  Application:  http://127.0.0.1:${APP_PORT}  (internal only)
  Service user: ${APP_USER}  (unprivileged, no login shell)
  Install dir:  ${APP_DIR}
  Data:         ${DATA_DIR}
  Backups:      ${BACKUP_DIR}
  Logs:         ${LOG_DIR}
  Service:      systemctl status TBM

${C_WARN}Next steps${C_RESET}
  1. Open the panel and sign in as administrator.
  2. Add backup sources and create your first job.
  3. Configure storage and Telegram destinations if needed.

${C_WARN}Important${C_RESET}
  • Back up ${APP_DIR}/.env — it contains the key used to decrypt stored
    credentials. Losing it makes saved secrets unrecoverable.
  • The service runs as '${APP_USER}' with no root privileges. To back up
    root-owned files, grant read access explicitly, for example:
        sudo usermod -aG www-data ${APP_USER}
    rather than running the service as root.
  • To remove the software: sudo ${APP_DIR}/scripts/uninstall.sh

EOF
