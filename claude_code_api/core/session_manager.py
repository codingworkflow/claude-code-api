"""Session management for Claude Code API Gateway."""

import asyncio
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional

import structlog

from claude_code_api.core.config import settings
from claude_code_api.core.database import db_manager
from claude_code_api.models.claude import get_default_model
from claude_code_api.utils.time import utc_now

logger = structlog.get_logger()


class SessionInfo:
    """Session information and metadata."""

    def __init__(
        self, session_id: str, project_id: str, model: str, system_prompt: str = None
    ):
        self.session_id = session_id
        self.project_id = project_id
        self.model = model
        self.system_prompt = system_prompt
        self.created_at = utc_now()
        self.updated_at = utc_now()
        self.message_count = 0
        self.total_tokens = 0
        self.total_cost = 0.0
        self.is_active = True


class SessionManager:
    """Manages active sessions and their lifecycle."""

    def __init__(self):
        self.active_sessions: Dict[str, SessionInfo] = {}
        self.cleanup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._start_cleanup_task()

    def _start_cleanup_task(self):
        """Start periodic cleanup task."""
        if self.cleanup_task is None or self.cleanup_task.done():
            self.cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def _periodic_cleanup(self):
        """Periodic cleanup of expired sessions."""
        while True:
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=settings.cleanup_interval_minutes * 60,
                )
                break
            except asyncio.TimeoutError:
                self.cleanup_expired_sessions()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Error in periodic cleanup", error=str(e))

    async def create_session(
        self,
        project_id: str,
        model: str = None,
        system_prompt: str = None,
        session_id: str = None,
    ) -> str:
        """Create new session."""
        if session_id is None:
            session_id = str(uuid.uuid4())

        # Create session info
        session_info = SessionInfo(
            session_id=session_id,
            project_id=project_id,
            model=model or get_default_model(),
            system_prompt=system_prompt,
        )

        # Store in active sessions
        self.active_sessions[session_id] = session_info

        # Create database record
        session_data = {
            "id": session_id,
            "project_id": project_id,
            "model": session_info.model,
            "system_prompt": system_prompt,
            "title": f"Session {session_id[:8]}",
            "created_at": session_info.created_at,
            "updated_at": session_info.updated_at,
        }

        await db_manager.create_session(session_data)

        logger.info(
            "Session created",
            session_id=session_id,
            project_id=project_id,
            model=session_info.model,
        )

        return session_id

    async def get_session(self, session_id: str) -> Optional[SessionInfo]:
        """Get session information."""
        # Check active sessions first
        if session_id in self.active_sessions:
            return self.active_sessions[session_id]

        # Load from database if not in memory
        db_session = await db_manager.get_session(session_id)
        if db_session and db_session.is_active:
            # Restore to active sessions
            session_info = SessionInfo(
                session_id=db_session.id,
                project_id=db_session.project_id,
                model=db_session.model,
                system_prompt=db_session.system_prompt,
            )
            session_info.created_at = db_session.created_at
            session_info.updated_at = db_session.updated_at
            session_info.message_count = db_session.message_count
            session_info.total_tokens = db_session.total_tokens
            session_info.total_cost = db_session.total_cost

            self.active_sessions[session_id] = session_info
            return session_info

        return None

    async def update_session(
        self,
        session_id: str,
        tokens_used: int = 0,
        cost: float = 0.0,
        message_content: str = None,
        role: str = "user",
    ):
        """Update session with new message and metrics."""
        session_info = await self.get_session(session_id)
        if not session_info:
            return

        # Update session info
        session_info.updated_at = utc_now()
        session_info.total_tokens += tokens_used
        session_info.total_cost += cost

        if message_content:
            session_info.message_count += 1

            # Add message to database
            message_data = {
                "session_id": session_id,
                "role": role,
                "content": message_content,
                "input_tokens": tokens_used if role == "user" else 0,
                "output_tokens": tokens_used if role == "assistant" else 0,
                "cost": cost,
                "created_at": utc_now(),
            }

            await db_manager.add_message(message_data)

        # Update database metrics
        await db_manager.update_session_metrics(session_id, tokens_used, cost)

        logger.debug(
            "Session updated",
            session_id=session_id,
            tokens_used=tokens_used,
            cost=cost,
            total_tokens=session_info.total_tokens,
        )

    def end_session(self, session_id: str):
        """End session and cleanup."""
        if session_id in self.active_sessions:
            session_info = self.active_sessions[session_id]
            session_info.is_active = False
            del self.active_sessions[session_id]

            logger.info(
                "Session ended",
                session_id=session_id,
                duration_minutes=(utc_now() - session_info.created_at).total_seconds()
                / 60,
                total_tokens=session_info.total_tokens,
                total_cost=session_info.total_cost,
            )

    def cleanup_expired_sessions(self):
        """Clean up expired sessions."""
        current_time = utc_now()
        timeout_delta = timedelta(minutes=settings.session_timeout_minutes)
        expired_sessions = []

        for session_id, session_info in self.active_sessions.items():
            if current_time - session_info.updated_at > timeout_delta:
                expired_sessions.append(session_id)

        for session_id in expired_sessions:
            self.end_session(session_id)
            logger.info("Session expired and cleaned up", session_id=session_id)

    async def cleanup_all(self):
        """Clean up all sessions."""
        session_ids = list(self.active_sessions.keys())
        for session_id in session_ids:
            self.end_session(session_id)

        if self.cleanup_task and not self.cleanup_task.done():
            self._shutdown_event.set()
            await self.cleanup_task

        logger.info("All sessions cleaned up")

    def get_active_session_count(self) -> int:
        """Get number of active sessions."""
        return len(self.active_sessions)

    def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics."""
        total_tokens = sum(s.total_tokens for s in self.active_sessions.values())
        total_cost = sum(s.total_cost for s in self.active_sessions.values())
        total_messages = sum(s.message_count for s in self.active_sessions.values())

        return {
            "active_sessions": len(self.active_sessions),
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "total_messages": total_messages,
            "models_in_use": list({s.model for s in self.active_sessions.values()}),
        }


class ConversationManager:
    """Manages conversation flow and context."""

    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager
        self.conversation_history: Dict[str, List[Dict[str, Any]]] = {}

    async def add_message(
        self, session_id: str, role: str, content: str, metadata: Dict[str, Any] = None
    ):
        """Add message to conversation history."""
        if session_id not in self.conversation_history:
            self.conversation_history[session_id] = []

        message = {
            "role": role,
            "content": content,
            "timestamp": utc_now().isoformat(),
            "metadata": metadata or {},
        }

        self.conversation_history[session_id].append(message)

        # Update session
        await self.session_manager.update_session(
            session_id=session_id, message_content=content, role=role
        )

    def get_conversation_history(
        self, session_id: str, limit: int = None
    ) -> List[Dict[str, Any]]:
        """Get conversation history for session."""
        history = self.conversation_history.get(session_id, [])
        if limit:
            return history[-limit:]
        return history

    def format_messages_for_claude(
        self, session_id: str, include_system: bool = True
    ) -> List[Dict[str, str]]:
        """Format messages for Claude Code input."""
        history = self.get_conversation_history(session_id)
        formatted = []

        for msg in history:
            if msg["role"] == "system" and not include_system:
                continue

            formatted.append({"role": msg["role"], "content": msg["content"]})

        return formatted

    def clear_conversation(self, session_id: str):
        """Clear conversation history."""
        if session_id in self.conversation_history:
            del self.conversation_history[session_id]

        self.session_manager.end_session(session_id)
