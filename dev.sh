#!/usr/bin/env bash
# Runs the Spring Boot API (port 8080) and the Next.js frontend (port 3000) together.
# The frontend proxies /api/* to API_URL, which defaults to the local backend here
# (next.config.mjs otherwise falls back to the Render deployment). Ctrl-C stops both.
set -eu
cd "$(dirname "$0")"

trap 'trap - INT TERM EXIT; kill 0' INT TERM EXIT

(cd API_Server && ./mvnw spring-boot:run) &
(cd frontend && API_URL="${API_URL:-http://localhost:8080}" npm run dev) &
wait
