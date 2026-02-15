# Claude Code API Gateway

OpenAI-compatible API gateway for Claude Code CLI.

## What You Get

- OpenAI-style endpoints (`/v1/chat/completions`, `/v1/models`, sessions/projects APIs)
- Streaming and non-streaming chat completions
- Claude model aliases and fallback behavior
- Optional `model` field: if omitted, CLI default model is used

## Quick Start (Linux/macOS)

```bash
git clone https://github.com/codingworkflow/claude-code-api
cd claude-code-api
make install
make start
```

Server URLs:
- API: `http://localhost:8000`
- OpenAPI docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`

## Quick Start (Windows)

Use the provided wrappers:

```bat
make.bat install
start.bat
```

Notes:
- `start.bat` starts the API in dev mode.
- `make.bat` provides common project commands.
- Claude Code CLI support on Windows may require WSL depending on your local setup.

## Supported Models

Model config is in `claude_code_api/config/models.json`.
Override with `CLAUDE_CODE_API_MODELS_PATH`.

- `claude-opus-4-6-20260205`
- `claude-opus-4-5-20251101`
- `claude-sonnet-4-5-20250929`
- `claude-haiku-4-5-20251001`

Alias/fallback behavior:
- `model` is optional in `/v1/chat/completions`.
- `opus`, `claude-opus-latest`, `claude-opus-4-6` resolve to Opus 4.6.
- If Opus 4.6 is rejected at runtime, gateway retries once with latest configured Opus 4.5.
- If all attempted models are rejected, API returns `400` with `error.code = model_not_supported`.

## API Usage

Chat completion:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Hello"}
    ]
  }'
```

List models:

```bash
curl http://localhost:8000/v1/models
```

Streaming:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-5-20250929",
    "messages": [{"role": "user", "content": "Tell me a joke"}],
    "stream": true
  }'
```

## Configuration

Common settings are in `claude_code_api/core/config.py`:
- `claude_binary_path`
- `project_root`
- `database_url`
- `require_auth`

## Bug Reports & Support

For `claude-code-api` and `ai-code-fusion`, use this discussion thread for bug reports and troubleshooting:

- https://github.com/codingworkflow/ai-code-fusion/discussions/151

## Developer Docs

For engineering workflows and internal commands:
- `docs/dev.md`

## License

This project is licensed under the GNU General Public License v3.0 - see the LICENSE file for details.
