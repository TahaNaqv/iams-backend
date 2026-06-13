#!/usr/bin/env bash
# Usage: ./deploy.sh
# Run from the iams-backend/ directory on your local machine.
# Requires passwordless SSH. One-time setup:
#   ssh-keygen -t ed25519
#   ssh-copy-id leadrisks.com_487i3cldg3e@161.97.101.121
set -e

SERVER_USER="leadrisks.com_487i3cldg3e"
SERVER_HOST="161.97.101.121"
SERVER_PATH="\$HOME/auditsence/iams-backend"
CONTAINER="iams-backend-backend-1"

echo "==> Copying .env to server..."
scp .env "$SERVER_USER@$SERVER_HOST:~/auditsence/iams-backend/.env"

echo "==> Deploying on server..."
ssh "$SERVER_USER@$SERVER_HOST" bash << 'ENDSSH'
  set -e
  cd ~/auditsence/iams-backend

  echo "  -> Pulling latest code..."
  git pull origin master

  echo "  -> Rebuilding and restarting containers..."
  # ``-f docker-compose.yml`` explicitly skips any docker-compose.override.yml.
  # The override exists for local-dev only (bind-mounts the host source onto
  # /app for live editing); on the server we want the immutable image with
  # its baked-in venv, otherwise Django imports fail.
  docker-compose -f docker-compose.yml up -d --build

  # Migrations run automatically inside the backend container entrypoint
  # (DJANGO_AUTO_MIGRATE=1 in compose). Don't ``docker exec`` another
  # migrate here — it races against the still-booting container's PID
  # namespace and fails with "setns process: exit status 1". The
  # entrypoint owns this responsibility.

  echo "  -> Waiting for backend health (up to 150s)..."
  for i in $(seq 1 50); do
    status="$(docker inspect --format '{{.State.Health.Status}}' iams-backend-backend-1 2>/dev/null || echo missing)"
    if [ "$status" = "healthy" ]; then
      echo "  -> Backend reports healthy."
      exit 0
    fi
    sleep 3
  done
  echo "  -> Backend did not reach healthy in 90s. Recent logs:"
  docker-compose -f docker-compose.yml logs --tail=80 backend
  exit 1
ENDSSH

echo "==> Done. Backend is live at https://api.auditsence.leadrisks.com"
