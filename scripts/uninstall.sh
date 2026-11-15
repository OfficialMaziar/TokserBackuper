#!/usr/bin/env bash
#
# Tokser Backup Manager — uninstaller
#
# Usage:
#   sudo ./scripts/uninstall.sh [--purge-data] [--yes]
#
# By default this REMOVES THE SOFTWARE BUT KEEPS YOUR BACKUPS.
# Nothing containing user data is deleted unless --purge-data is given and
# you confirm interactively.
#
set -Eeuo pipefail

APP_USER="TBM"
APP_DIR="/opt/tokser-backup-manager"
BACKUP_DIR="/var/backups/tokser"
PURGE_DATA=0
ASSUME_YES=0

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_OK=$'\033[32m'; C_WARN=$'\033[33m'
  C_ERR=$'\033[31m'; C_BOLD=$'\033[1m'
else
  C_RESET=""; C_OK=""; C_WARN=""; C_ERR=""; C_BOLD=""
fi
ok()   { printf "%s  ✔ %s%s\n" "${C_OK}" "$*" "${C_RESET}"; }
warn() { printf "%s  ! %s%s\n" "${C_WARN}" "$*" "${C_RESET}"; }
die()  { printf "%s  ✘ %s%s\n" "${C_ERR}" "$*" "${C_RESET}" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge-data) PURGE_DATA=1; shift ;;
    --yes|-y)     ASSUME_YES=1; shift ;;
    -h|--help)    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)            die "Unknown option: $1" ;;
  esac
done

[[ "${EUID}" -eq 0 ]] || die "Run as root (use sudo)."

# Enumerate what will be deleted.
VICTIMS=()
# Handle both the current unit name (TBM.service) and the older one so
# upgrades from an earlier release uninstall cleanly.
for unit in /etc/systemd/system/TBM.service /etc/systemd/system/tokser-backup-manager.service; do
  [[ -f "${unit}" ]] && VICTIMS+=("${unit}")
done
[[ -f /etc/nginx/sites-available/tokser-backup-manager ]] && VICTIMS+=("/etc/nginx/sites-available/tokser-backup-manager")
[[ -L /etc/nginx/sites-enabled/tokser-backup-manager ]] && VICTIMS+=("/etc/nginx/sites-enabled/tokser-backup-manager")
[[ -d "${APP_DIR}" ]] && VICTIMS+=("${APP_DIR} (application + data + logs)")

cat <<EOF

${C_BOLD}Tokser Backup Manager — uninstall${C_RESET}

The following will be removed:
EOF
for v in "${VICTIMS[@]}"; do printf "  • %s\n" "$v"; done || true

if [[ ${#VICTIMS[@]} -eq 0 ]]; then
  warn "Nothing appears to be installed."
  exit 0
fi

ARCHIVE_COUNT=0
ARCHIVE_BYTES=0
if [[ -d "${BACKUP_DIR}" ]]; then
  ARCHIVE_COUNT="$(find "${BACKUP_DIR}" -type f \( -name '*.tar' -o -name '*.tar.gz' -o -name '*.zip' -o -name '*.zst' -o -name '*.enc' \) 2>/dev/null | wc -l)"
  ARCHIVE_BYTES="$(du -sb "${BACKUP_DIR}" 2>/dev/null | awk '{print $1}')"
  ARCHIVE_BYTES="${ARCHIVE_BYTES:-0}"
  printf "\n%sYour backups at %s: %s file(s), %s bytes — KEPT unless --purge-data is given.%s\n" \
    "${C_WARN}" "${BACKUP_DIR}" "${ARCHIVE_COUNT}" "${ARCHIVE_BYTES}" "${C_RESET}"
fi

if [[ "${ASSUME_YES}" -eq 0 ]]; then
  read -r -p "Proceed with uninstall? [y/N] " reply
  [[ "${reply}" =~ ^[Yy]$ ]] || die "Aborted — nothing was changed."
fi

# Stop and disable the service.
if [[ -f /etc/systemd/system/TBM.service || -f /etc/systemd/system/tokser-backup-manager.service ]]; then
  for svc in TBM tokser-backup-manager; do
    systemctl stop "${svc}.service" 2>/dev/null || true
    systemctl disable "${svc}.service" 2>/dev/null || true
  done
  rm -f /etc/systemd/system/TBM.service /etc/systemd/system/tokser-backup-manager.service
  systemctl daemon-reload
  ok "Service stopped and removed"
fi

# Nginx.
if [[ -L /etc/nginx/sites-enabled/tokser-backup-manager ]]; then
  rm -f /etc/nginx/sites-enabled/tokser-backup-manager
fi
if [[ -f /etc/nginx/sites-available/tokser-backup-manager ]]; then
  rm -f /etc/nginx/sites-available/tokser-backup-manager
fi
if command -v nginx >/dev/null && nginx -t >/dev/null 2>&1; then
  systemctl reload nginx 2>/dev/null || true
  ok "Nginx configuration removed"
fi

# Application directory.
if [[ -d "${APP_DIR}" ]]; then
  if [[ "${PURGE_DATA}" -eq 1 ]]; then
    if [[ "${ASSUME_YES}" -eq 0 ]]; then
      warn "This also deletes the database, .env secrets and local archives in ${APP_DIR}."
      read -r -p "Type DELETE to confirm permanent deletion: " confirm
      [[ "${confirm}" == "DELETE" ]] || die "Aborted — application directory preserved."
    fi
    rm -rf "${APP_DIR}"
    ok "Application directory deleted"
  else
    # Keep the data and .env, remove only code.
    if [[ -d "${APP_DIR}/data" || -d "${APP_DIR}/backups" ]]; then
      TARBALL="/root/tokser-backup-manager-data-$(date +%Y%m%d-%H%M%S).tar.gz"
      tar -czf "${TARBALL}" -C "${APP_DIR}" data backups .env config.yaml 2>/dev/null || true
      [[ -f "${TARBALL}" ]] && ok "Data archived to ${TARBALL}"
    fi
    rm -rf "${APP_DIR}"
    ok "Application removed (data preserved in the archive above and in ${BACKUP_DIR})"
  fi
fi

# Backups directory is only removed with an explicit second confirmation.
if [[ "${PURGE_DATA}" -eq 1 && -d "${BACKUP_DIR}" ]]; then
  if [[ "${ASSUME_YES}" -eq 0 ]]; then
    warn "Deleting ${BACKUP_DIR} removes ${ARCHIVE_COUNT} backup archive(s) permanently."
    read -r -p "Type DELETE-BACKUPS to confirm: " confirm2
    if [[ "${confirm2}" == "DELETE-BACKUPS" ]]; then
      rm -rf "${BACKUP_DIR}"
      ok "Backup directory deleted"
    else
      warn "Backup directory preserved"
    fi
  else
    rm -rf "${BACKUP_DIR}"
    ok "Backup directory deleted"
  fi
elif [[ -d "${BACKUP_DIR}" ]]; then
  ok "Backups preserved at ${BACKUP_DIR}"
fi

# ACLs granted to the service account must not outlive it. Removing the user
# orphans the ACEs (they show up as numeric UIDs), so revoke them first.
if command -v setfacl >/dev/null 2>&1 && id -u "${APP_USER}" >/dev/null 2>&1; then
  revoked=0
  for target in /root /var/www /var/lib/mysql /etc/nginx /etc/apache2; do
    [[ -e "${target}" ]] || continue
    if getfacl -p -c "${target}" 2>/dev/null | grep -q "^user:${APP_USER}:"; then
      setfacl -x "u:${APP_USER}" "${target}" 2>/dev/null && {
        find "${target}" -xdev -type d -exec setfacl -x "u:${APP_USER}" {} + 2>/dev/null || true
        revoked=$((revoked + 1))
      }
    fi
  done
  if [[ "${revoked}" -gt 0 ]]; then
    ok "Revoked ACL access on ${revoked} path(s)"
  fi
fi

# Service user.
if id -u "${APP_USER}" >/dev/null 2>&1; then
  if [[ "${PURGE_DATA}" -eq 1 ]]; then
    userdel "${APP_USER}" 2>/dev/null || warn "Could not delete user '${APP_USER}' (still owns files?)"
    ok "Service user deleted"
  else
    warn "Service user '${APP_USER}' kept (owns preserved data)"
    warn "Its ACL entries were left in place; remove with: tbm access revoke <path>"
  fi
fi

cat <<EOF

${C_OK}${C_BOLD}Uninstall complete.${C_RESET}

EOF
