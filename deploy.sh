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
CONTAINER="iams-backend_backend_1"

echo "==> Copying .env to server..."
scp .env "$SERVER_USER@$SERVER_HOST:~/auditsence/iams-backend/.env"

echo "==> Deploying on server..."
ssh "$SERVER_USER@$SERVER_HOST" bash << ENDSSH
  set -e
  cd ~/auditsence/iams-backend

  echo "  -> Pulling latest code..."
  git pull origin master

  echo "  -> Rebuilding and restarting containers..."
  docker-compose up -d --build

  echo "  -> Running migrations..."
  docker exec $CONTAINER uv run python manage.py migrate
ENDSSH

echo "==> Done. Backend is live at https://api.auditsence.leadrisks.com"
