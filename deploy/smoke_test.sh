#!/usr/bin/env bash
#
# Post-deploy smoke test. Hit the canonical paths from the *public*
# URL (so we exercise the full nginx → backend pipeline, not just
# container-local checks).
#
# Exit codes:
#   0 — all checks passed
#   1 — at least one check failed (the script reports which)
#
# Environment:
#   IAMS_BASE_URL  — the public origin (https://iams.internal etc.)

set -uo pipefail

: "${IAMS_BASE_URL:?required}"

CURL="curl -sS --fail-with-body --max-time 10"
fail=0

check() {
  local name="$1" url="$2" expected="${3:-200}"
  local status
  status="$($CURL -o /tmp/smoke.body -w '%{http_code}' "$url" || true)"
  if [[ "$status" == "$expected" ]]; then
    echo "[ok]   $name ($status)"
  else
    echo "[FAIL] $name expected $expected got $status"
    cat /tmp/smoke.body || true
    fail=1
  fi
}

echo "[smoke] target=${IAMS_BASE_URL}"
check "GET /health/"  "${IAMS_BASE_URL}/health/"
check "GET /ready/"   "${IAMS_BASE_URL}/ready/"
check "GET /metrics"  "${IAMS_BASE_URL}/metrics"
check "GET /api/schema/ (OpenAPI)" "${IAMS_BASE_URL}/api/schema/"
check "GET / (FE index)"  "${IAMS_BASE_URL}/"
# Unauth API access returns 401 → that's a sign auth is wired.
check "GET /api/audits/ requires auth" "${IAMS_BASE_URL}/api/audits/" 401

if (( fail == 0 )); then
  echo "[smoke] ✅ all checks passed"
  exit 0
fi
echo "[smoke] ❌ one or more checks failed"
exit 1
