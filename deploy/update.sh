#!/usr/bin/env bash
# Deploy a new version. Run from /opt/lyfe on the server.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml"

echo "→ pulling code"
git pull --ff-only

echo "→ building"
$COMPOSE build

echo "→ migrating database"
$COMPOSE run --rm bot alembic upgrade head

echo "→ restarting"
$COMPOSE up -d

echo "→ running containers"
$COMPOSE ps
