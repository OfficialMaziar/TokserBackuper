#!/usr/bin/env bash
#
# Tokser Backup Manager — health check
# Exit code 0 = healthy, 1 = unhealthy. Suitable for monitoring systems.
#
# Usage: ./scripts/healthcheck.sh [port]
#
set -Eeuo pipefail

PORT="${1:-8000}"
URL="http://127.0.0.1:${PORT}/api/v1/health"

response="$(curl -fsS --max-time 10 "${URL}" 2>/dev/null)" || {
  echo "UNHEALTHY: no response from ${URL}"
  exit 1
}

# Extract "status" without requiring jq.
status="$(printf '%s' "${response}" | sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
db="$(printf '%s' "${response}" | sed -n 's/.*"database"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"

if [[ "${status}" == "ok" && "${db}" == "ok" ]]; then
  echo "HEALTHY: status=${status} database=${db}"
  exit 0
fi

echo "UNHEALTHY: status=${status:-unknown} database=${db:-unknown}"
echo "${response}"
exit 1
