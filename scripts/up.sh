#!/usr/bin/env bash
# Start the local Zammad, make its admin and an API token the first time, and write the token to .env.
# Every secret is generated here and stays in the git-ignored files docker/.env and .env; none is printed.
set -euo pipefail
cd "$(dirname "$0")/.."
dc() { docker compose -f docker/compose.yml -f docker/compose.override.yml --env-file docker/.env "$@"; }

if [ ! -f docker/.env ]; then
  cat > docker/.env <<ENV
POSTGRES_PASS=$(openssl rand -hex 16)
POSTGRES_SUPERUSER_PASS=$(openssl rand -hex 16)
ELASTICSEARCH_ENABLED=false
TZ=Asia/Riyadh
RESTART=unless-stopped
ADMIN_PASSWORD=$(openssl rand -hex 16)
ENV
fi

dc up -d
echo "waiting for Zammad (first start takes a few minutes)…"
for _ in $(seq 1 180); do
  curl -fsS -o /dev/null http://127.0.0.1:8090/ 2>/dev/null && break
  sleep 3
done

if ! grep -q '^ZAMMAD_TOKEN=' .env 2>/dev/null; then
  pw=$(grep '^ADMIN_PASSWORD=' docker/.env | cut -d= -f2)
  token=$(ADMIN_PASSWORD="$pw" dc exec -T -e ADMIN_PASSWORD zammad-railsserver bundle exec rails r "$(cat scripts/setup.rb)" | tail -1)
  case "$token" in TOKEN=*) ;; *) echo "could not create the API token" >&2; exit 1 ;; esac
  { echo "ZAMMAD_URL=http://127.0.0.1:8090"; echo "ZAMMAD_TOKEN=${token#TOKEN=}"; } >> .env
  echo "admin and API token created (in docker/.env and .env)"
fi
echo "Zammad is up at http://localhost:8090"
