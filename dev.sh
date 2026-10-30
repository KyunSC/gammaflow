#!/usr/bin/env bash
# Runs the Spring Boot API (port 8080) and the Next.js frontend (port 3000) together.
# The frontend proxies /api/* to API_URL, which defaults to the local backend here
# (next.config.mjs otherwise falls back to the Render deployment). Ctrl-C stops both.
# Market data (Yahoo, Databento, ThetaData) can't be redistributed, so only local
# runs use it: GAMMAFLOW_DATA=real makes the frontend proxy /api/* to the backend
# instead of serving synthetic data (frontend/lib/dataSource.mjs; a hosted build
# refuses it). TICK_PROFILE_ENABLED turns on the backend's licensed tick profiles
# and NEXT_PUBLIC_TICK_SOURCE=real makes the chart use them instead of simulated prints.
set -eu
cd "$(dirname "$0")"

trap 'trap - INT TERM EXIT; kill 0' INT TERM EXIT

(cd API_Server && TICK_PROFILE_ENABLED=true ./mvnw spring-boot:run) &
(cd frontend && GAMMAFLOW_DATA=real API_URL="${API_URL:-http://localhost:8080}" NEXT_PUBLIC_TICK_SOURCE=real npm run dev) &
wait
