#!/usr/bin/env bash
#
# Tokser Backup Manager - remote installer entry point
#
#   curl -fsSL https://raw.githubusercontent.com/OfficialMaziar/TokserBackuper/main/install.sh | sudo bash
#
# With options (note the `-s --`):
#   curl -fsSL .../install.sh | sudo bash -s -- --http-port 7676 --domain backup.example.com
#
# Or download first, then run:
#   curl -fsSL .../install.sh -o tbm-install.sh
#   sudo bash tbm-install.sh
#
# This file only bootstraps: it downloads the repository and hands control to
# scripts/install.sh inside it.
#
set -Eeuo pipefail

REPO="${TBM_REPO:-OfficialMaziar/TokserBackuper}"
REF="${TBM_REF:-main}"

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_OK=$'\033[32m'; C_WARN=$'\033[33m'
  C_ERR=$'\033[31m'; C_BOLD=$'\033[1m'
else
  C_RESET=""; C_OK=""; C_WARN=""; C_ERR=""; C_BOLD=""
fi
say()  { printf "%s==> %s%s\n" "${C_BOLD}" "$*" "${C_RESET}"; }
ok()   { printf "%s  ✔ %s%s\n" "${C_OK}" "$*" "${C_RESET}"; }
warn() { printf "%s  ! %s%s\n" "${C_WARN}" "$*" "${C_RESET}"; }
die()  { printf "%s  ✘ %s%s\n" "${C_ERR}" "$*" "${C_RESET}" >&2; exit 1; }

cat <<'BANNER'

  ______      __                 ____             __
  /_  __/__  / /__  ___________ / __ )____ ______/ /_
   / / / _ \/ / _ \/ ___/ ___/ / __  / __ `/ ___/ __ \
  / / /  __/ /  __(__  |__  ) / /_/ / /_/ / /__/ / / /
 /_/  \___/_/\___/____/____(_)_____/\__,_/\___/_/ /_/

  Tokser Backup Manager - by TokserTeam

BANNER

[[ "${EUID}" -eq 0 ]] || die "This installer must run as root. Re-run it with sudo."

command -v curl >/dev/null 2>&1 || die "curl is required. Install it with: apt-get install -y curl"

WORKDIR="$(mktemp -d /tmp/tbm-bootstrap.XXXXXX)"
cleanup() { rm -rf "${WORKDIR}"; }
trap cleanup EXIT

# --- download the project ------------------------------------------------
say "Downloading ${REPO} (${REF})"

DOWNLOADED=0
if command -v git >/dev/null 2>&1; then
  if git clone --depth 1 --branch "${REF}" "https://github.com/${REPO}.git" \
        "${WORKDIR}/src" >/dev/null 2>&1; then
    DOWNLOADED=1
    ok "Cloned with git"
  else
    warn "git clone failed - trying the source archive"
  fi
fi

if [[ "${DOWNLOADED}" -eq 0 ]]; then
  URL="https://codeload.github.com/${REPO}/tar.gz/refs/heads/${REF}"
  if ! curl -fsSL "${URL}" -o "${WORKDIR}/src.tar.gz" 2>/dev/null; then
    URL="https://codeload.github.com/${REPO}/tar.gz/${REF}"
    curl -fsSL "${URL}" -o "${WORKDIR}/src.tar.gz" \
      || die "Could not download ${REPO} (${REF}). Verify the repository name and network access."
  fi
  mkdir -p "${WORKDIR}/unpack"
  tar -xzf "${WORKDIR}/src.tar.gz" -C "${WORKDIR}/unpack" \
    || die "The downloaded archive could not be extracted"
  INNER="$(find "${WORKDIR}/unpack" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [[ -n "${INNER}" ]] || die "Unexpected archive layout"
  mv "${INNER}" "${WORKDIR}/src"
  ok "Downloaded archive"
fi

[[ -f "${WORKDIR}/src/scripts/install.sh" ]] \
  || die "scripts/install.sh missing - is ${REPO} the right repository?"
chmod +x "${WORKDIR}/src/scripts/install.sh"

# --- hand over -----------------------------------------------------------
say "Launching the installer"
cd "${WORKDIR}/src"

# stdin is the piped script, so the interactive prompts need /dev/tty.
if [[ -r /dev/tty ]]; then
  exec bash "${WORKDIR}/src/scripts/install.sh" "$@" </dev/tty
else
  warn "No terminal attached - running non-interactively"
  exec bash "${WORKDIR}/src/scripts/install.sh" --non-interactive "$@"
fi
