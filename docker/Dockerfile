FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    bash \
    ca-certificates \
    curl \
    git \
    jq \
    python3 \
    python3-pip \
    python3-venv \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash claudeuser && \
    echo "claudeuser ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Set up application directory
WORKDIR /home/claudeuser/app
COPY . /home/claudeuser/app
RUN chown -R claudeuser:claudeuser /home/claudeuser/app

USER claudeuser

# Install Claude CLI using the official installer (no npm required)
RUN curl -fsSL https://claude.ai/install.sh | bash

# Create virtualenv and install dependencies
RUN python3 -m venv /home/claudeuser/venv && \
    /home/claudeuser/venv/bin/pip install --upgrade pip setuptools wheel && \
    /home/claudeuser/venv/bin/pip install -e . --use-pep517 || \
    /home/claudeuser/venv/bin/pip install -e .

ENV PATH="/home/claudeuser/venv/bin:/home/claudeuser/.local/bin:/home/claudeuser/.bun/bin:${PATH}"

# Create Claude config and workspace directories
RUN mkdir -p /home/claudeuser/.config/claude /home/claudeuser/app/workspace

EXPOSE 8000

ENV HOST=0.0.0.0
ENV PORT=8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

RUN cat <<'EOF' > /home/claudeuser/entrypoint.sh
#!/usr/bin/env bash
set -euo pipefail

auth_ready=false

# Prefer host-mounted Claude auth (Claude Max / Claude Code)
if [ -d "$HOME/.claude" ] && [ -n "$(ls -A "$HOME/.claude" 2>/dev/null)" ]; then
  echo "Using Claude auth from $HOME/.claude"
  auth_ready=true
fi

# Fallback to Claude config file if present
if [ "$auth_ready" != "true" ] && [ -f "$HOME/.config/claude/config.json" ]; then
  echo "Using Claude config from $HOME/.config/claude/config.json"
  auth_ready=true
fi

# Optionally write config from API key (only when explicitly requested)
if [ "$auth_ready" != "true" ] && [ -n "${ANTHROPIC_API_KEY:-}" ] && [ "${USE_CLAUDE_MAX:-}" != "true" ]; then
  if [ "${WRITE_CLAUDE_CONFIG:-}" = "true" ]; then
    echo "Configuring Claude Code with API key..."
    python3 - <<'PY'
import json
import os
from pathlib import Path

config_dir = Path.home() / ".config" / "claude"
config_dir.mkdir(parents=True, exist_ok=True)
with (config_dir / "config.json").open("w", encoding="utf-8") as handle:
    json.dump({"apiKey": os.environ["ANTHROPIC_API_KEY"], "autoUpdate": False}, handle)
PY
    echo "Claude Code configured with API key"
    auth_ready=true
  else
    echo "ANTHROPIC_API_KEY is set but WRITE_CLAUDE_CONFIG is not true."
    echo "For security, no config file was written. Mount ~/.claude or ~/.config/claude or set WRITE_CLAUDE_CONFIG=true."
  fi
fi

if [ "$auth_ready" != "true" ] && [ "${USE_CLAUDE_MAX:-}" = "true" ]; then
  echo "Using Claude Max subscription - please run: docker exec -it claude-code-api claude"
  echo "Then authenticate via browser when prompted"
elif [ "$auth_ready" != "true" ]; then
  echo "No authentication configured. Mount ~/.claude or ~/.config/claude, or set ANTHROPIC_API_KEY + WRITE_CLAUDE_CONFIG=true."
fi

echo "Starting API server..."
cd /home/claudeuser/app
exec python3 -m claude_code_api.main
EOF
RUN chmod +x /home/claudeuser/entrypoint.sh

ENTRYPOINT ["/home/claudeuser/entrypoint.sh"]
