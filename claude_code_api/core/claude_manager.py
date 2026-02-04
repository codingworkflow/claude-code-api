"""Claude Code process management."""

import asyncio
import json
import os
import subprocess
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

import structlog

from claude_code_api.models.claude import get_default_model

from .config import settings
from .security import ensure_directory_within_base

logger = structlog.get_logger()


class ClaudeProcess:
    """Manages a single Claude Code process."""

    def __init__(
        self,
        session_id: str,
        project_path: str,
        on_cli_session_id: Optional[Callable[[str], None]] = None,
        on_end: Optional[Callable[["ClaudeProcess"], None]] = None,
    ):
        self.session_id = session_id
        self.cli_session_id: Optional[str] = None
        self.project_path = project_path
        self.process: Optional[asyncio.subprocess.Process] = None
        self.is_running = False
        self.output_queue = asyncio.Queue()
        self.error_queue = asyncio.Queue()
        self._output_task: Optional[asyncio.Task] = None
        self._error_task: Optional[asyncio.Task] = None
        self._on_cli_session_id = on_cli_session_id
        self._on_end = on_end

    async def start(
        self, prompt: str, model: str = None, system_prompt: str = None
    ) -> bool:
        """Start Claude Code process and wait for completion."""
        try:
            # Prepare real command - using exact format from working Claudia example
            cmd = [settings.claude_binary_path]
            cmd.extend(["-p", prompt])

            if system_prompt:
                cmd.extend(["--system-prompt", system_prompt])

            if model:
                cmd.extend(["--model", model])

            # Always use stream-json output format (exact order from working example)
            cmd.extend(
                [
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    "--dangerously-skip-permissions",
                ]
            )

            logger.info(
                "Starting Claude process",
                session_id=self.session_id,
                project_path=self.project_path,
                model=model or get_default_model(),
            )

            # Start process from src directory (where Claude works without API key)
            src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            logger.info(f"Starting Claude from directory: {src_dir}")
            logger.info(f"Command: {' '.join(cmd)}")

            # Start process asynchronously
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=src_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
            )

            self.is_running = True

            # Start background tasks to read output
            self._output_task = asyncio.create_task(self._read_output())
            self._error_task = asyncio.create_task(self._read_error())

            return True

        except Exception as e:
            logger.error(
                "Failed to start Claude process",
                session_id=self.session_id,
                error=str(e),
            )
            return False

    def _decode_output_line(self, line: bytes) -> Optional[Dict[str, Any]]:
        line_text = line.decode().strip()
        if not line_text:
            return None

        payload = line_text
        if payload.startswith("data: "):
            payload = payload[6:].strip()
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {"type": "text", "content": line_text}

    async def _read_output(self):
        """Read stdout from process line by line."""
        claude_session_id = None

        try:
            while self.is_running and self.process:
                line = await self.process.stdout.readline()
                if not line:
                    break

                data = self._decode_output_line(line)
                if not data:
                    continue

                # Extract Claude's session ID from the first message
                if not claude_session_id and data.get("session_id"):
                    claude_session_id = data["session_id"]
                    logger.info(
                        "Extracted Claude session ID", session_id=claude_session_id
                    )
                    self.cli_session_id = claude_session_id
                    if self._on_cli_session_id:
                        self._on_cli_session_id(claude_session_id)

                await self.output_queue.put(data)
        except Exception as e:
            logger.error("Error reading output", error=str(e))
        finally:
            await self.output_queue.put(None)
            self.is_running = False

            logger.info(
                "Claude process output stream ended", session_id=self.session_id
            )
            if self._on_end:
                self._on_end(self)

    async def _read_error(self):
        """Read stderr from process."""
        try:
            while self.is_running and self.process:
                line = await self.process.stderr.readline()
                if not line:
                    break

                error_text = line.decode().strip()
                if error_text:
                    logger.warning("Claude stderr", message=error_text)
        except Exception as e:
            logger.error("Error reading stderr", error=str(e))

    async def get_output(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Get output from Claude process."""
        while True:
            try:
                # Wait for output with timeout
                output = await asyncio.wait_for(
                    self.output_queue.get(), timeout=settings.streaming_timeout_seconds
                )

                if output is None:  # End signal
                    break

                yield output

            except asyncio.TimeoutError:
                logger.warning("Output timeout", session_id=self.session_id)
                break
            except Exception as e:
                logger.error(
                    "Error getting output", session_id=self.session_id, error=str(e)
                )
                break

    async def send_input(self, text: str):
        """Send input to Claude process."""
        if self.process and self.process.stdin and self.is_running:
            try:
                self.process.stdin.write((text + "\n").encode())
                await self.process.stdin.drain()
            except Exception as e:
                logger.error(
                    "Error sending input", session_id=self.session_id, error=str(e)
                )

    async def stop(self):
        """Stop Claude process."""
        self.is_running = False

        for task in (self._output_task, self._error_task):
            if task and not task.done():
                task.cancel()

        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
            except Exception as e:
                logger.error(
                    "Error stopping process", session_id=self.session_id, error=str(e)
                )
            finally:
                self.process = None
                self._output_task = None
                self._error_task = None

        logger.info("Claude process stopped", session_id=self.session_id)


class ClaudeManagerError(RuntimeError):
    """Base error for Claude manager operations."""


class ClaudeBinaryNotFoundError(ClaudeManagerError):
    """Raised when the Claude binary cannot be located."""


class ClaudeVersionError(ClaudeManagerError):
    """Raised when the Claude version cannot be determined."""


class ClaudeConcurrencyError(ClaudeManagerError):
    """Raised when the concurrent session limit is exceeded."""


class ClaudeProcessStartError(ClaudeManagerError):
    """Raised when a Claude process fails to start."""


class ClaudeManager:
    """Manages multiple Claude Code processes."""

    def __init__(self):
        self.processes: Dict[str, ClaudeProcess] = {}
        self.cli_session_index: Dict[str, str] = {}
        self.max_concurrent = settings.max_concurrent_sessions

    async def get_version(self) -> str:
        """Get Claude Code version."""
        try:
            result = await asyncio.create_subprocess_exec(
                settings.claude_binary_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await result.communicate()

            if result.returncode == 0:
                version = stdout.decode().strip()
                return version
            error = stderr.decode().strip()
            raise ClaudeVersionError(f"Claude version check failed: {error}")

        except FileNotFoundError as exc:
            raise ClaudeBinaryNotFoundError(
                f"Claude binary not found at: {settings.claude_binary_path}"
            ) from exc
        except OSError as exc:
            raise ClaudeVersionError(
                f"Failed to get Claude version: {str(exc)}"
            ) from exc

    async def create_session(
        self,
        session_id: str,
        project_path: str,
        prompt: str,
        model: str = None,
        system_prompt: str = None,
        on_cli_session_id: Optional[Callable[[str], None]] = None,
    ) -> ClaudeProcess:
        """Create new Claude session."""
        # Check concurrent session limit
        if len(self.processes) >= self.max_concurrent:
            raise ClaudeConcurrencyError(
                f"Maximum concurrent sessions ({self.max_concurrent}) reached"
            )

        # Ensure project directory exists
        os.makedirs(project_path, exist_ok=True)

        # Create process
        def _handle_cli_session_id(cli_session_id: str):
            self._register_cli_session(session_id, cli_session_id)
            if on_cli_session_id:
                on_cli_session_id(cli_session_id)

        process = ClaudeProcess(
            session_id=session_id,
            project_path=project_path,
            on_cli_session_id=_handle_cli_session_id,
            on_end=self._cleanup_process,
        )

        # Start process
        success = await process.start(
            prompt=prompt,
            model=model or get_default_model(),
            system_prompt=system_prompt,
        )

        if not success:
            raise ClaudeProcessStartError("Failed to start Claude process")

        self.processes[session_id] = process

        logger.info(
            "Claude session created",
            session_id=process.session_id,
            active_sessions=len(self.processes),
        )

        return process

    def get_session(self, session_id: str) -> Optional[ClaudeProcess]:
        """Get existing Claude session."""
        resolved_id = self._resolve_session_id(session_id)
        if not resolved_id:
            return None
        return self.processes.get(resolved_id)

    async def stop_session(self, session_id: str):
        """Stop Claude session."""
        resolved_id = self._resolve_session_id(session_id)
        if resolved_id and resolved_id in self.processes:
            process = self.processes[resolved_id]
            await process.stop()
            self._cleanup_process(process)

            logger.info(
                "Claude session stopped",
                session_id=resolved_id,
                active_sessions=len(self.processes),
            )

    async def cleanup_all(self):
        """Stop all Claude sessions."""
        for session_id in tuple(self.processes):
            await self.stop_session(session_id)

        logger.info("All Claude sessions cleaned up")

    def get_active_sessions(self) -> List[str]:
        """Get list of active session IDs."""
        return list(self.processes.keys())

    async def continue_conversation(self, session_id: str, prompt: str) -> bool:
        """Continue existing conversation."""
        resolved_id = self._resolve_session_id(session_id)
        if not resolved_id:
            return False
        process = self.processes.get(resolved_id)
        if not process:
            return False

        await process.send_input(prompt)
        return True

    def _register_cli_session(self, api_session_id: str, cli_session_id: str):
        if not cli_session_id:
            return
        self.cli_session_index[cli_session_id] = api_session_id

    def _resolve_session_id(self, session_id: str) -> Optional[str]:
        if session_id in self.processes:
            return session_id
        return self.cli_session_index.get(session_id)

    def _cleanup_process(self, process: ClaudeProcess):
        api_session_id = process.session_id
        if api_session_id in self.processes:
            del self.processes[api_session_id]
        if process.cli_session_id:
            self.cli_session_index.pop(process.cli_session_id, None)


# Utility functions for project management
def create_project_directory(project_id: str) -> str:
    """Create project directory."""
    return ensure_directory_within_base(project_id, settings.project_root)


def cleanup_project_directory(project_path: str):
    """Clean up project directory."""
    try:
        import shutil

        if os.path.exists(project_path):
            shutil.rmtree(project_path)
            logger.info("Project directory cleaned up", path=project_path)
    except Exception as e:
        logger.error(
            "Failed to cleanup project directory", path=project_path, error=str(e)
        )


def validate_claude_binary() -> bool:
    """Validate Claude binary availability."""
    try:
        result = subprocess.run(
            [settings.claude_binary_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False
