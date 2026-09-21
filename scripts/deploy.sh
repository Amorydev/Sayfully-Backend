#!/usr/bin/env bash
# Deploy bản mới trên VPS: pull → build → migrate → up → health. Chạy từ thư mục repo.
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE="docker compose -f compose.prod.yml"

git pull --ff-only
$COMPOSE build api
$COMPOSE run --rm api python manage.py migrate --noinput
$COMPOSE up -d --remove-orphans

for _ in $(seq 1 20); do
  if $COMPOSE exec -T api curl -fsS http://localhost:8000/health/ >/dev/null 2>&1; then
    echo "OK $(git rev-parse --short HEAD)"; exit 0
  fi
  sleep 3
done
echo "health check thất bại — xem: $COMPOSE logs --tail 100 api" >&2
exit 1
