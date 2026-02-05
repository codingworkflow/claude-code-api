#!/usr/bin/env bash
set -e

# SonarCloud-specific environment loader
echo "Loading SonarCloud configuration..."

# Load base .env file
if [ -f .env ]; then
    echo "Loading base environment from .env"
    # Source with automatic export
    set -a
    . ./.env 2>/dev/null || true
    set +a
fi

# Load SonarCloud-specific .env.cloud file
if [ -f .env.cloud ]; then
    echo "Loading SonarCloud configuration from .env.cloud"
    set -a
    . ./.env.cloud 2>/dev/null || true
    set +a
fi

# Verify VAULT_ADDR is set
if [ -z "${VAULT_ADDR:-}" ]; then
    echo "Error: VAULT_ADDR not set"
    echo "   Ensure .env sets VAULT_ADDR"
    exit 1
fi

echo "Using Vault: $VAULT_ADDR"

# Load SONAR_CLOUD_TOKEN from Vault (different path than regular SONAR_TOKEN)
echo "Loading SONAR_CLOUD_TOKEN from Vault..."

# Try the correct Vault path - adjust for your organization
CLOUD_SECRET=$(vault kv get -field=token kv/sonarcloud 2>/dev/null || echo "")

if [ -n "$CLOUD_SECRET" ]; then
    export SONAR_CLOUD_TOKEN="$CLOUD_SECRET"
    echo "SONAR_CLOUD_TOKEN loaded from Vault (path: kv/sonarcloud)"
else
    echo "SONAR_CLOUD_TOKEN not found in Vault at kv/sonarcloud"
    echo "   Tried path: kv/sonarcloud"
    echo "   Set SONAR_CLOUD_TOKEN manually or add secret to Vault"
fi

# Check if we have required configuration
if [ -z "${SONAR_CLOUD_TOKEN:-}" ]; then
    echo "Error: SONAR_CLOUD_TOKEN not set"
    echo "   Configure one of the following:"
    echo "   1. Add secret to Vault at: kv/sonarcloud"
    echo "   2. Set environment variable: export SONAR_CLOUD_TOKEN=your-token"
    echo "   3. Add to .env.cloud: SONAR_CLOUD_TOKEN=your-token"
    exit 1
fi

# Set defaults if not provided
SONAR_HOST_URL="${SONAR_HOST_URL:-${SONAR_CLOUD_URL:-https://sonarcloud.io}}"
SONAR_ORG="${SONAR_ORG:-${SONAR_CLOUD_ORG:-}}"
SONAR_PROJECT_KEY="${SONAR_PROJECT_KEY:-${SONAR_CLOUD_PROJECT:-claude-code-api}}"

# Generate coverage for SonarCloud
echo "Generating coverage report for SonarCloud..."
mkdir -p dist/quality/coverage dist/quality/sonar
python -m pytest \
    --cov=claude_code_api \
    --cov-report=xml:dist/quality/coverage/coverage.xml \
    --cov-report=term-missing \
    --junitxml=dist/quality/sonar/xunit-report.xml \
    -v tests/

echo "Running SonarCloud scanner..."
echo "   Organization: $SONAR_ORG"
echo "   Project Key: $SONAR_PROJECT_KEY"
echo "   Host URL: $SONAR_HOST_URL"

# Run sonar-scanner with SonarCloud settings
sonar-scanner \
    -Dsonar.host.url="$SONAR_HOST_URL" \
    -Dsonar.token="$SONAR_CLOUD_TOKEN" \
    -Dsonar.organization="$SONAR_ORG" \
    -Dsonar.projectKey="$SONAR_PROJECT_KEY" \
    -Dsonar.projectVersion="$(cat VERSION 2>/dev/null || echo "1.0.0")" \
    -Dsonar.projectBaseDir=. \
    -Dsonar.scm.provider=git \
    -Dsonar.working.directory=dist/quality/sonar/scannerwork
