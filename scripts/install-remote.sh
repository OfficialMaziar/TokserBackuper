#!/usr/bin/env bash
#
# Tokser Backup Manager - one-line remote installer
#
#   curl -fsSL https://raw.githubusercontent.com/OfficialMaziar/TokserBackuper/main/install.sh | sudo bash
#
# Downloads the project from GitHub into a temporary directory and runs the
# regular installer. All arguments are forwarded, for example:
#
#   curl -fsSL .../install.sh | sudo bash -s -- --http-port 7676
#
# Environment overrides:
#   TBM_REPO    Git URL or owner/name      (default: OfficialMaziar/TokserBackuper)
#   TBM_REF     Branch, tag or commit      (default: main)
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

[[ "${EUID}" -eq 0 ]] || die "Run as root:  curl -fsSL <url> | sudo bash"

command -v curl >/dev/null || die "curl is required"
command -v tar  >/dev/null || die "tar is required"

# --- fetch ---------------------------------------------------------------
WORKDIR="$(mktemp -d /tmp/tbm-install.XXXXXX)"
trap 'rm -rf "${WORKDIR}"' EXIT

if command -v git >/dev/null; then
  say "Downloading ${REPO} (${REF})"
  git clone --depth 1 --branch "${REF}" "https://github.com/${REPO}.git" "${WORKDIR}/src" \
    >/dev/null 2>&1 || warn "git clone failed - falling back to the release archive"
fi

if [[ ! -d "${WORKDIR}/src" ]]; then
  say "Downloading archive ${REPO}@${REF}"
  TARBALL="https://codeload.github.com/${REPO}/tar.gz/refs/heads/${REF}"
  if ! curl -fsSL "${TARBALL}" -o "${WORKDIR}/src.tar.gz"; then
    # A tag or commit is not under refs/heads; try the generic endpoint.
    TARBALL="https://codeload.github.com/${REPO}/tar.gz/${REF}"
    curl -fsSL "${TARBALL}" -o "${WORKDIR}/src.tar.gz" \
      || die "Could not download ${REPO} (${REF}). Check the repository name and your network."
  fi
  mkdir -p "${WORKDIR}/extract"
  tar -xzf "${WORKDIR}/src.tar.gz" -C "${WORKDIR}/extract" \
    || die "The downloaded archive is not a valid tarball"
  # The archive contains a single top-level directory.
  INNER="$(find "${WORKDIR}/extract" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [[ -n "${INNER}" ]] || die "Unexpected archive layout"
  mv "${INNER}" "${WORKDIR}/src"
fi

[[ -f "${WORKDIR}/src/scripts/install.sh" ]] \
  || die "Installation script not found — is this the TokserBackuper repository?"

ok "Source ready"
chmod +x "${WORKDIR}/src/scripts/install.sh"

# --- run -----------------------------------------------------------------
# The installer asks for ports and an administrator password, but stdin is the
# pipe this script arrived on. Reattach the controlling terminal when one
# exists; otherwise run non-interactively.
say "Starting the installer"
if [[ -r /dev/tty ]]; then
  exec bash "${WORKDIR}/src/scripts/install.sh" "$@" </dev/tty
else
  warn "No terminal available - running non-interactively"
  exec bash "${WORKDIR}/src/scripts/install.sh" --non-interactive "$@"
fi
