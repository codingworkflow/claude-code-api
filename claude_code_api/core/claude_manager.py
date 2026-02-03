"""Claude Code process management."""

import asyncio
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Dict, List, AsyncGenerator, Any
import structlog

from .config import settings

logger = structlog.get_logger()


class ClaudeProcess:
    """Manages a single Claude Code process."""
    
    def __init__(self, session_id: str, project_path: str):
        self.session_id = session_id
        self.project_path = project_path
        self.process: Optional[asyncio.subprocess.Process] = None
        self.is_running = False
        self.output_queue = asyncio.Queue()
        self.error_queue = asyncio.Queue()
        
    async def start(
        self, 
        prompt: str, 
        model: str = None,
        system_prompt: str = None,
        resume_session: str = None
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
            cmd.extend([
                "--output-format", "stream-json",
                "--verbose", 
                "--dangerously-skip-permissions"
            ])
            
            logger.info(
                "Starting Claude process",
                session_id=self.session_id,
                project_path=self.project_path,
                model=model or settings.default_model
            )
            
            # Start process from src directory (where Claude works without API key)
            src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            logger.info(f"Starting Claude from directory: {src_dir}")
            logger.info(f"Command: {' '.join(cmd)}")
            
            # Start process asynchronously
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=src_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE
            )
            
            self.is_running = True
            
            # Start background tasks to read output
            asyncio.create_task(self._read_output())
            asyncio.create_task(self._read_error())
            
            return True
            
        except Exception as e:
            logger.error(
                "Failed to start Claude process",
                session_id=self.session_id,
                error=str(e)
            )
            return False

    async def _read_output(self):
        """Read stdout from process line by line."""
        claude_session_id = None

        try:
            while self.is_running and self.process:
                line = await self.process.stdout.readline()
                if not line:
                    break

                line_text = line.decode().strip()
                if not line_text:
                    continue

                try:
                    data = json.loads(line_text)
                    # Extract Claude's session ID from the first message
                    if not claude_session_id and data.get("session_id"):
                        claude_session_id = data["session_id"]
                        logger.info(f"Extracted Claude session ID: {claude_session_id}")
                        # Update our session_id to match Claude's
                        self.session_id = claude_session_id
                    await self.output_queue.put(data)
                except json.JSONDecodeError:
                    # Handle non-JSON output
                    await self.output_queue.put({"type": "text", "content": line_text})
        except Exception as e:
            logger.error("Error reading output", error=str(e))
        finally:
            await self.output_queue.put(None)
            self.is_running = False

            # Wait for process to exit
            if self.process:
                try:
                    # Don't wait forever, just check if it's done or wait a bit
                    # But actually we should let it run until it's done or stopped
                    pass
                except Exception:
                    pass

            logger.info(
                "Claude process output stream ended",
                session_id=self.session_id
            )

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
                    self.output_queue.get(),
                    timeout=settings.streaming_timeout_seconds
                )
                
                if output is None:  # End signal
                    break
                    
                yield output
                
            except asyncio.TimeoutError:
                logger.warning(
                    "Output timeout",
                    session_id=self.session_id
                )
                break
            except Exception as e:
                logger.error(
                    "Error getting output",
                    session_id=self.session_id,
                    error=str(e)
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
                    "Error sending input",
                    session_id=self.session_id,
                    error=str(e)
                )
    
    async def _start_mock_process(self, prompt: str, model: str):
        """Start mock process for testing."""
        self.is_running = True
        
        # Create mock Claude response
        mock_response = {
            "type": "result",
            "sessionId": self.session_id,
            "model": model or "claude-3-5-haiku-20241022",
            "message": {
                "role": "assistant", 
                "content": f"Hello! You said: '{prompt}'. This is a mock response from Claude Code API Gateway."
            },
            "usage": {
                "input_tokens": len(prompt.split()),
                "output_tokens": 15,
                "total_tokens": len(prompt.split()) + 15
            },
            "cost_usd": 0.001,
            "duration_ms": 100
        }
        
        # Put the response in the queue
        await self.output_queue.put(mock_response)
        await self.output_queue.put(None)  # End signal
    
    async def stop(self):
        """Stop Claude process."""
        self.is_running = False
        
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
            except Exception as e:
                logger.error(
                    "Error stopping process",
                    session_id=self.session_id,
                    error=str(e)
                )
            finally:
                self.process = None
        
        logger.info(
            "Claude process stopped",
            session_id=self.session_id
        )


class ClaudeManager:
    """Manages multiple Claude Code processes."""
    
    def __init__(self):
        self.processes: Dict[str, ClaudeProcess] = {}
        self.max_concurrent = settings.max_concurrent_sessions
    
    async def get_version(self) -> str:
        """Get Claude Code version."""
        try:
            result = await asyncio.create_subprocess_exec(
                settings.claude_binary_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await result.communicate()
            
            if result.returncode == 0:
                version = stdout.decode().strip()
                return version
            else:
                error = stderr.decode().strip()
                raise Exception(f"Claude version check failed: {error}")
                
        except FileNotFoundError:
            raise Exception(f"Claude binary not found at: {settings.claude_binary_path}")
        except Exception as e:
            raise Exception(f"Failed to get Claude version: {str(e)}")
    
    async def create_session(
        self,
        session_id: str,
        project_path: str,
        prompt: str,
        model: str = None,
        system_prompt: str = None,
        resume_session: str = None
    ) -> ClaudeProcess:
        """Create new Claude session."""
        # Check concurrent session limit
        if len(self.processes) >= self.max_concurrent:
            raise Exception(f"Maximum concurrent sessions ({self.max_concurrent}) reached")
        
        # Ensure project directory exists
        os.makedirs(project_path, exist_ok=True)
        
        # Create process
        process = ClaudeProcess(session_id, project_path)
        
        # Start process
        success = await process.start(
            prompt=prompt,
            model=model or settings.default_model,
            system_prompt=system_prompt,
            resume_session=resume_session
        )
        
        if not success:
            raise Exception("Failed to start Claude process")
        
        # Don't store processes since Claude CLI completes immediately
        # This prevents the "max concurrent sessions" error
        
        logger.info(
            "Claude session created",
            session_id=process.session_id,  # Use Claude's actual session ID
            active_sessions=len(self.processes)
        )
        
        return process
    
    async def get_session(self, session_id: str) -> Optional[ClaudeProcess]:
        """Get existing Claude session."""
        return self.processes.get(session_id)
    
    async def stop_session(self, session_id: str):
        """Stop Claude session."""
        if session_id in self.processes:
            process = self.processes[session_id]
            await process.stop()
            del self.processes[session_id]
            
            logger.info(
                "Claude session stopped",
                session_id=session_id,
                active_sessions=len(self.processes)
            )
    
    async def cleanup_all(self):
        """Stop all Claude sessions."""
        for session_id in list(self.processes.keys()):
            await self.stop_session(session_id)
        
        logger.info("All Claude sessions cleaned up")
    
    def get_active_sessions(self) -> List[str]:
        """Get list of active session IDs."""
        return list(self.processes.keys())
    
    async def continue_conversation(
        self,
        session_id: str,
        prompt: str
    ) -> bool:
        """Continue existing conversation."""
        process = self.processes.get(session_id)
        if not process:
            return False
        
        await process.send_input(prompt)
        return True


# Utility functions for project management
def create_project_directory(project_id: str) -> str:
    """Create project directory."""
    project_path = os.path.join(settings.project_root, project_id)
    os.makedirs(project_path, exist_ok=True)
    return project_path


def cleanup_project_directory(project_path: str):
    """Clean up project directory."""
    try:
        import shutil
        if os.path.exists(project_path):
            shutil.rmtree(project_path)
            logger.info("Project directory cleaned up", path=project_path)
    except Exception as e:
        logger.error("Failed to cleanup project directory", path=project_path, error=str(e))


def validate_claude_binary() -> bool:
    """Validate Claude binary availability."""
    try:
        result = subprocess.run(
            [settings.claude_binary_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False
