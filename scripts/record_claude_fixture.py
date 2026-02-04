#!/usr/bin/env python3
"""Record Claude CLI stream-json output into a sanitized fixture."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any


def _replace_in_obj(value: Any, needle: str, replacement: str) -> Any:
    if isinstance(value, str):
        return value.replace(needle, replacement)
    if isinstance(value, list):
        return [_replace_in_obj(item, needle, replacement) for item in value]
    if isinstance(value, dict):
        return {k: _replace_in_obj(v, needle, replacement) for k, v in value.items()}
    return value


def _sanitize_event(event: dict, cwd_path: str | None, session_id: str | None) -> dict:
    if session_id:
        event["session_id"] = session_id
    if cwd_path:
        if event.get("cwd") == cwd_path:
            event["cwd"] = "."
        event = _replace_in_obj(event, cwd_path, ".")
    return event


def _run_claude(args: list[str], cwd: str | None) -> bytes:
    result = subprocess.run(
        args,
        cwd=cwd or None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Claude CLI failed: {stderr.strip()}")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description="Record Claude stream-json output to a fixture.")
    parser.add_argument("--prompt", required=True, help="Prompt to send to Claude.")
    parser.add_argument("--out", required=True, help="Output JSONL fixture path.")
    parser.add_argument("--model", default="", help="Claude model id or alias.")
    parser.add_argument("--claude-bin", default=os.getenv("CLAUDE_BINARY_PATH", "claude"))
    parser.add_argument("--session-id", default="", help="Stable session id to embed in fixture.")
    parser.add_argument("--cwd", default="", help="Working directory for Claude CLI.")
    parser.add_argument("--permission-mode", default="bypassPermissions")
    parser.add_argument("--include-partial-messages", action="store_true")
    parser.add_argument("--tools", default="", help="Comma-separated tool list for Claude CLI.")
    args = parser.parse_args()

    cmd = [
        args.claude_bin,
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if args.model:
        cmd.extend(["--model", args.model])
    if args.permission_mode:
        cmd.extend(["--permission-mode", args.permission_mode])
    if args.include_partial_messages:
        cmd.append("--include-partial-messages")
    if args.tools != "":
        cmd.extend(["--tools", args.tools])
    if args.session_id:
        cmd.extend(["--session-id", args.session_id])
    cmd.append(args.prompt)

    cwd = args.cwd or None
    raw = _run_claude(cmd, cwd)
    if not raw.strip():
        raise RuntimeError("Claude CLI returned empty output.")

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    cwd_path = os.path.abspath(cwd) if cwd else None
    session_id = args.session_id or None

    lines = raw.splitlines()
    with open(out_path, "w", encoding="utf-8") as handle:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            payload = line
            if payload.startswith(b"data: "):
                payload = payload[6:]
            event = json.loads(payload.decode("utf-8"))
            event = _sanitize_event(event, cwd_path, session_id)
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    print(f"Wrote fixture to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
