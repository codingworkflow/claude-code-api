#!/usr/bin/env bash
set -e

# Load environment if .env exists
if [ -f .env ]; then
    echo "Loading environment overrides from .env"
    # Source .env with automatic export
    set -a
    . ./.env || true  # Don't fail if there are warnings
    set +a

    # Verify critical variables are set
    if [ -z "${DTRACK_API_KEY:-}" ]; then
        echo "Warning: DTRACK_API_KEY not set, cannot upload SBOM" >&2
        echo "Set DTRACK_API_KEY in .env or via Vault" >&2
        exit 1
    fi
    if [ -z "${DTRACK_BASE_URL:-}" ]; then
        echo "Warning: DTRACK_BASE_URL not set" >&2
        exit 1
    fi
fi

# Check required variables
if [ -z "${DTRACK_BASE_URL:-}" ]; then
    echo "Error: DTRACK_BASE_URL is not set" >&2
    exit 1
fi

if [ -z "${DTRACK_API_KEY:-}" ]; then
    echo "Error: DTRACK_API_KEY is not set" >&2
    exit 1
fi

PROJECT="${DTRACK_PROJECT:-claude-code-api}"
VERSION="${DTRACK_PROJECT_VERSION:-$(git rev-parse --short HEAD 2>/dev/null || echo "dev")}"
BASE_URL="${DTRACK_BASE_URL%/}"
SBOM_FILE="${1:-dist/security/sbom/sbom.json}"

echo "Uploading SBOM to $BASE_URL"
echo "   Project: $PROJECT"
echo "   Version: $VERSION"
echo "   File: $SBOM_FILE"

if [ ! -f "$SBOM_FILE" ]; then
    echo "Error: SBOM file not found at $SBOM_FILE" >&2
    echo "Run 'make sbom' first to generate the SBOM" >&2
    exit 1
fi

BOM_B64=$(base64 < "$SBOM_FILE" | tr -d '\n')
TMP_RESP=$(mktemp)

# Try JSON upload first
JSON_PAYLOAD=$(jq -n \
    --arg pn "$PROJECT" \
    --arg pv "$VERSION" \
    --arg bom "$BOM_B64" \
    '{projectName: $pn, projectVersion: $pv, autoCreate: true, bom: $bom}')

upload_json() {
    curl -sS -o "$TMP_RESP" -w "%{http_code}" -X PUT \
        -H "X-Api-Key: $DTRACK_API_KEY" \
        -H "Content-Type: application/json" \
        -d "$JSON_PAYLOAD" \
        "$BASE_URL/api/v1/bom"
}

status=$(upload_json || echo "curl_failed")
if [ "$status" != "curl_failed" ] && [ "$status" -ge 200 ] && [ "$status" -lt 300 ]; then
    echo "SBOM uploaded to $BASE_URL (JSON)"
    rm -f "$TMP_RESP"
    exit 0
fi

echo "Dependency-Track JSON upload failed (status=$status):"
if [ -f "$TMP_RESP" ]; then cat "$TMP_RESP"; fi

# Try multipart form upload
echo "Retrying with multipart form upload..."
status=$(curl -sS -o "$TMP_RESP" -w "%{http_code}" -X PUT \
    -H "X-Api-Key: $DTRACK_API_KEY" \
    -F "projectName=$PROJECT" \
    -F "projectVersion=$VERSION" \
    -F "autoCreate=true" \
    -F "bom@$SBOM_FILE;type=application/json" \
    "$BASE_URL/api/v1/bom" || echo "curl_failed")

if [ "$status" != "curl_failed" ] && [ "$status" -ge 200 ] && [ "$status" -lt 300 ]; then
    echo "SBOM uploaded to $BASE_URL (multipart)"
    rm -f "$TMP_RESP"
    exit 0
fi

echo "Dependency-Track upload failed (status=$status). Response:"
cat "$TMP_RESP" 2>/dev/null || true
rm -f "$TMP_RESP"
exit 1
