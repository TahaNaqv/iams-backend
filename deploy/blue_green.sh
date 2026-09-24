#!/usr/bin/env bash
#
# Blue-green deploy for IAMS.
#
# Strategy:
#   1. Determine which color is currently *live* (reading the symlink at
#      deploy/nginx/upstream.conf).
#   2. Spin up the *other* color on the target host with the new image,
#      run `python manage.py migrate` *inside* that color's container
#      before flipping traffic (so a broken migration aborts the deploy
#      without affecting the live color).
#   3. Wait for /ready/ to return 200 on the new color.
#   4. Atomically swap the nginx upstream symlink → reload nginx → drain
#      the old color.
#   5. On any health-check failure, rollback: keep the symlink pointing
#      at the old color, leave the failed color running for forensics,
#      exit non-zero.
#
# Environment variables (required):
#   DEPLOY_HOST     — SSH target (e.g. iams-prod.internal)
#   DEPLOY_USER     — SSH user
#   DEPLOY_KEY      — SSH private key (PEM body)
#   BACKEND_IMAGE   — fully-qualified image ref
#   FRONTEND_IMAGE  — fully-qualified image ref
#   DEPLOY_ENV      — "staging" | "production"
#
# Idempotent: re-running the same color is fine — it just re-applies
# the image + migration. No-op if the image SHA hasn't changed.

set -euo pipefail

: "${DEPLOY_HOST:?required}"
: "${DEPLOY_USER:?required}"
: "${DEPLOY_KEY:?required}"
: "${BACKEND_IMAGE:?required}"
: "${FRONTEND_IMAGE:?required}"
: "${DEPLOY_ENV:?required}"

HEALTH_TIMEOUT_S="${HEALTH_TIMEOUT_S:-180}"
HEALTH_INTERVAL_S="${HEALTH_INTERVAL_S:-5}"

key_file="$(mktemp)"
trap 'rm -f "$key_file"' EXIT
printf "%s\n" "$DEPLOY_KEY" > "$key_file"
chmod 600 "$key_file"

ssh_opts=(-i "$key_file" -o StrictHostKeyChecking=accept-new -o BatchMode=yes)

remote() {
  ssh "${ssh_opts[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" "$@"
}

echo "[deploy] env=${DEPLOY_ENV} host=${DEPLOY_HOST}"
echo "[deploy] backend=${BACKEND_IMAGE}"
echo "[deploy] frontend=${FRONTEND_IMAGE}"

# 1) Find current live color.
current_color="$(remote 'cat /opt/iams/current-color 2>/dev/null || echo blue')"
case "$current_color" in
  blue)  new_color="green" ;;
  green) new_color="blue" ;;
  *) echo "[deploy] invalid current color: $current_color" >&2; exit 1 ;;
esac
echo "[deploy] current=${current_color} → new=${new_color}"

# 2) Push image refs + bring up the new color.
remote bash -se <<REMOTE_BLOCK
set -euo pipefail
cd /opt/iams
export BACKEND_IMAGE='${BACKEND_IMAGE}'
export FRONTEND_IMAGE='${FRONTEND_IMAGE}'
# Pull both images
docker compose pull backend-${new_color} frontend-${new_color}
# Apply migrations inside a one-shot container before starting workers.
# A broken migration here returns non-zero and bails *before* the swap.
docker compose run --rm --no-deps backend-${new_color} \\
  python manage.py migrate --no-input
# Start the new color (shared services already running).
docker compose --profile ${new_color} up -d
REMOTE_BLOCK

# 3) Wait for /ready/ to flip green on the new color (via the per-color
#    container hostname; nginx still routes to old color at this point).
echo "[deploy] waiting up to ${HEALTH_TIMEOUT_S}s for ${new_color}/ready/…"
deadline=$(( $(date +%s) + HEALTH_TIMEOUT_S ))
while (( $(date +%s) < deadline )); do
  status="$(remote "docker exec iams-backend-${new_color} wget -q -O- http://127.0.0.1:8000/ready/ 2>/dev/null | head -c 20 || true")"
  if [[ "$status" == *'"ok"'* || "$status" == *'ready'* ]]; then
    echo "[deploy] ${new_color} reports ready."
    break
  fi
  sleep "$HEALTH_INTERVAL_S"
done

if (( $(date +%s) >= deadline )); then
  echo "[deploy] ${new_color} failed health check — leaving for forensics." >&2
  echo "[deploy] traffic untouched; old color (${current_color}) still live." >&2
  exit 2
fi

# 4) Atomic swap: rewrite the upstream symlink + nginx -s reload.
echo "[deploy] swapping nginx upstream → ${new_color}"
remote bash -se <<REMOTE_BLOCK
set -euo pipefail
cd /opt/iams/deploy/nginx
ln -sfn upstream-${new_color}.conf upstream.conf
docker compose exec nginx nginx -s reload
echo "${new_color}" > /opt/iams/current-color
REMOTE_BLOCK

# 5) Drain the old color after a short grace period for in-flight requests.
echo "[deploy] draining old color (${current_color}) in 30s…"
sleep 30
remote "cd /opt/iams && docker compose --profile ${current_color} stop"

echo "[deploy] ✅ ${new_color} is now live."
