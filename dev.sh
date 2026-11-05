#!/usr/bin/env bash
# Runs the Spring Boot API (port 8080) and the Next.js frontend (port 3000) together.
# The frontend proxies /api/* to API_URL, which defaults to the local backend here
# (next.config.mjs otherwise falls back to the Render deployment). Ctrl-C stops both.
# Databento trade prints are licensed, so only local runs serve and show them:
# TICK_PROFILE_ENABLED turns on the backend's tick profiles and
# NEXT_PUBLIC_TICK_SOURCE=real makes the chart use them instead of simulated prints.
set -eu
cd "$(dirname "$0")"

trap 'trap - INT TERM EXIT; kill 0' INT TERM EXIT

# Read SUPABASE_PASSWORD from the repo-root .env with shell semantics (quotes,
# escapes) and hand it to Spring as a real env var. spring-dotenv's parser can
# read quoted/escaped values differently from the shell. Only this one key is
# exported, so other .env entries (e.g. API_URL) don't change dev.sh behaviour.
if [ -z "${SUPABASE_PASSWORD:-}" ] && [ -f .env ]; then
  SUPABASE_PASSWORD="$(set +u; set -a; . ./.env >/dev/null 2>&1; printf '%s' "${SUPABASE_PASSWORD:-}")"
  [ -n "$SUPABASE_PASSWORD" ] && export SUPABASE_PASSWORD
fi

(cd API_Server && TICK_PROFILE_ENABLED=true ./mvnw spring-boot:run) &
(cd frontend && API_URL="${API_URL:-http://localhost:8080}" NEXT_PUBLIC_TICK_SOURCE=real npm run dev) &
wait
