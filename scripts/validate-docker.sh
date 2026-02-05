#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="${DOCKER_PROJECT_NAME:-claude-code-api-validate}"
COMPOSE_FILE="docker/docker-compose.yml"
HEALTH_URL="${DOCKER_HEALTH_URL:-http://localhost:8000/health}"
BASE_URL="${DOCKER_BASE_URL:-http://localhost:8000}"
MAX_RETRIES="${DOCKER_HEALTH_RETRIES:-30}"
SLEEP_SECONDS="${DOCKER_HEALTH_SLEEP:-2}"
E2E_MODEL_ID="${DOCKER_E2E_MODEL_ID:-claude-haiku-4-5-20251001}"

cleanup() {
  docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Building Docker image..."
docker build -f docker/Dockerfile -t claude-code-api:docker-validate .

echo "Validating docker-compose configuration..."
docker compose -f "$COMPOSE_FILE" config >/dev/null

echo "Starting Docker stack for end-to-end validation..."
docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" up -d --build

echo "Waiting for API health check at $HEALTH_URL..."
healthy=false
for _ in $(seq 1 "$MAX_RETRIES"); do
  if curl -fsS "$HEALTH_URL" >/dev/null; then
    healthy=true
    break
  fi
  sleep "$SLEEP_SECONDS"
done

if [ "$healthy" != "true" ]; then
  echo "API did not become healthy in time. Logs:" >&2
  docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" logs --no-color >&2 || true
  exit 1
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  has_auth=false
  if [ -d "claude-config" ] && [ -n "$(ls -A claude-config 2>/dev/null)" ]; then
    has_auth=true
  fi
  if [ -d "${HOME}/.claude" ] && [ -n "$(ls -A "${HOME}/.claude" 2>/dev/null)" ]; then
    has_auth=true
  fi
  if [ "$has_auth" != "true" ]; then
    echo "E2E tests require authentication. Set ANTHROPIC_API_KEY or provide ./claude-config or ~/.claude with Claude credentials." >&2
    exit 1
  fi
fi

echo "Running E2E tests against $BASE_URL with model $E2E_MODEL_ID..."
CLAUDE_CODE_API_E2E=1 \
CLAUDE_CODE_API_BASE_URL="$BASE_URL" \
CLAUDE_CODE_API_TEST_MODEL="$E2E_MODEL_ID" \
python -m pytest tests/test_e2e_live_api.py -m e2e -v

echo "Docker build, compose config, API health, and E2E tests validated."
