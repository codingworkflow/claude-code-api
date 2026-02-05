#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SONAR_DIR="${SONAR_DIR:-dist/quality/sonar}"
COVERAGE_DIR="${COVERAGE_DIR:-dist/quality/coverage}"
VERSION="${VERSION:-1.0.0}"

mkdir -p "$SONAR_DIR" "$COVERAGE_DIR"

echo "Generating coverage report for SonarQube..."
python -m pytest \
  --cov=claude_code_api \
  --cov-report=xml:"$COVERAGE_DIR/coverage.xml" \
  --cov-report=term-missing \
  --junitxml="$SONAR_DIR/xunit-report.xml" \
  -v tests/

if ! command -v sonar-scanner >/dev/null 2>&1; then
  echo "sonar-scanner not found. Install with: brew install sonar-scanner or download from https://docs.sonarqube.org/latest/analysis/scan/sonarscanner/"
  exit 1
fi

if [ -f ".env.vault" ]; then
  . ./.env.vault
fi

if [ -f ".env" ]; then
  set -a
  . ./.env
  set +a
fi

if [ -n "${VAULT_SECRET_PATHS:-}" ] || [ -n "${VAULT_REQUIRED_VARS:-}" ]; then
  if [ -f "./scripts/vault-helper.sh" ]; then
    . ./scripts/vault-helper.sh
    vault_helper::load_from_definitions \
      "${VAULT_SECRET_PATHS:-}" \
      "${VAULT_REQUIRED_VARS:-}" \
      "${VAULT_TOKEN_FILE:-}"
  else
    echo "Error: vault-helper.sh is required when VAULT_SECRET_PATHS or VAULT_REQUIRED_VARS is set." >&2
    echo "Missing helper: ./scripts/vault-helper.sh" >&2
    echo "VAULT_SECRET_PATHS=${VAULT_SECRET_PATHS:-<empty>}" >&2
    echo "VAULT_REQUIRED_VARS=${VAULT_REQUIRED_VARS:-<empty>}" >&2
    exit 1
  fi
fi

SONAR_HOST_URL="${SONAR_HOST_URL:-${SONAR_URL:-}}"
if [ -z "$SONAR_HOST_URL" ]; then
  echo "SONAR_URL or SONAR_HOST_URL is required (e.g., https://sonarcloud.io or https://sonar.local)"
  exit 1
fi

case "$SONAR_HOST_URL" in
  http://*|https://*) ;;
  *)
    echo "SONAR_URL must include http(s) scheme: $SONAR_HOST_URL"
    exit 1
    ;;
esac

if [ -z "${SONAR_TOKEN:-}" ]; then
  echo "SONAR_TOKEN not set - proceeding without authentication"
fi

sonar-scanner \
  -Dsonar.host.url="$SONAR_HOST_URL" \
  -Dsonar.token="$SONAR_TOKEN" \
  -Dsonar.projectVersion="$VERSION" \
  -Dsonar.working.directory="$SONAR_DIR/scannerwork"
