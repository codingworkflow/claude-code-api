# Development Guide

This document contains developer workflows (setup, QA, linting, testing, Sonar).

## Prerequisites

- Python 3.11+
- Claude Code CLI available in your shell (`claude --version`)
- GNU Make (Linux/macOS) or `make.bat` (Windows)

## Setup

Linux/macOS:

```bash
make install-dev
```

Windows:

```bat
make.bat install-dev
```

## Core Commands

Linux/macOS (`Makefile`):

```bash
make install
make install-dev
make start
make start-prod
make test
make test-no-cov
make fmt
make lint
make vet
```

Windows (`make.bat`):

```bat
make.bat install
make.bat install-dev
make.bat start
make.bat start-prod
make.bat test
make.bat test-no-cov
make.bat fmt
make.bat lint
```

## QA / Validation

Lint and format:

```bash
make fmt
make lint
```

Run tests:

```bash
make test
```

## SonarQube

Generate coverage + run Sonar scan:

```bash
make sonar
```

Coverage-only artifacts for Sonar:

```bash
make coverage-sonar
```

## CI Matrix Testing

- Cross-platform install and API smoke checks run in `.github/workflows/install-matrix.yml`.
- Matrix coverage includes:
  - OS: `ubuntu-latest`, `macos-latest`, `windows-latest`
  - Python: `3.11`, `3.12`
  - Install modes: explicit PEP 517 editable and editable fallback path (`pip install -e .`)
- The workflow runs deterministic tests with `pytest -m "not e2e"` and targeted API smoke checks for `/health` and `/v1/models`.

Optional live validation (manual only):

- Trigger `Install Matrix + API Smoke` via `workflow_dispatch`.
- Set `run_live_claude=true`.
- Provide repository secret `ANTHROPIC_API_KEY`.
- Optional input `live_model` defaults to `claude-haiku-4-5-20251001`.
- The live job is non-blocking (`continue-on-error`) while reliability is being established.

## Logging

- Logging is configured centrally in `claude_code_api/core/logging_config.py`.
- Default log file: `dist/logs/claude-code-api.log`.
- Rotation is enabled via `log_max_bytes` and `log_backup_count` settings.
- Default runtime behavior logs startup/shutdown lifecycle and errors only.
- Set `debug=true` for extended logging.

## Windows Notes

- `start.bat` is a convenience wrapper for `make.bat start`.
- If Claude CLI is unavailable on native Windows in your environment, run the project in WSL.
