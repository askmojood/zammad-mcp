#!/usr/bin/env bash
# Start over: delete the local Zammad and its data, set it up again, and fill it with the SAMPLE desk.
set -euo pipefail
cd "$(dirname "$0")/.."
dc() { docker compose -f docker/compose.yml -f docker/compose.override.yml --env-file docker/.env "$@"; }
[ -f docker/.env ] && dc down -v
rm -f .env docker/.env docker/backdate.json
./scripts/up.sh
set -a; . ./.env; set +a
uv run zammad-seed
dc exec -T zammad-railsserver bundle exec rails r "$(cat scripts/backdate.rb)" < docker/backdate.json
