#!/bin/bash
# Installs dependencies so tests run in Claude Code cloud sessions.
# Local sessions are skipped: dev machines already have their own toolchains/venvs.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

# Frontend (Next.js + node:test engine tests). npm install, not ci, so the
# cached container keeps node_modules between sessions.
(cd frontend && npm install --no-audit --no-fund)

# Python: Azure Functions tests and the lightweight functions/ml research tests.
# Deliberately omits the heavy training deps (torch, rtdl, shap, jupyter); install
# those on demand from functions/ml/requirements.txt. `python3 -m pip` so the packages
# land in the interpreter the tests run under; PIP_BREAK_SYSTEM_PACKAGES lets it install
# into a PEP 668 "externally managed" system Python in the throwaway container.
PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip install --quiet --disable-pip-version-check \
  numpy pandas scipy pyarrow pytz python-dotenv scikit-learn matplotlib psycopg2-binary \
  yfinance databento thetadata

# Spring Boot API: pre-fetch Maven dependencies and compile. Prefer a system mvn: the wrapper's
# own distribution download (wget) can fail behind the cloud egress proxy.
MVN=./mvnw
command -v mvn >/dev/null 2>&1 && MVN=mvn
(cd API_Server && $MVN -q -B test-compile) || \
  echo "warning: Maven dependency pre-fetch failed; API_Server tests may need network" >&2
