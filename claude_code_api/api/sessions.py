"""Sessions API endpoint - Extension to OpenAI API."""

from typing import List, Dict, Any
from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import JSONResponse
import structlog

from claude_code_api.models.openai import (
    SessionInfo,
    CreateSessionRequest,
    PaginatedResponse,
    PaginationInfo
)
from claude_code_api.core.session_manager import SessionManager

logger = structlog.get_logger()
router = APIRouter()


@router.get("/sessions", response_model=PaginatedResponse)
async def list_sessions(
    page: int = 1,
    per_page: int = 20,
    project_id: str = None,
    req: Request = None
) -> PaginatedResponse:
    """List all sessions."""
    
    session_manager: SessionManager = req.app.state.session_manager
    
    # Get active sessions
    active_sessions = []
    for session_id, session_info in session_manager.active_sessions.items():
        if project_id is None or session_info.project_id == project_id:
            session_data = SessionInfo(
                id=session_info.session_id,
                project_id=session_info.project_id,
                title=f"Session {session_info.session_id[:8]}",
                model=session_info.model,
                system_prompt=session_info.system_prompt,
                created_at=session_info.created_at,
                updated_at=session_info.updated_at,
                is_active=session_info.is_active,
                total_tokens=session_info.total_tokens,
                total_cost=session_info.total_cost,
                message_count=session_info.message_count
            )
            active_sessions.append(session_data)
    
    # Simple pagination
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_sessions = active_sessions[start_idx:end_idx]
    
    pagination = PaginationInfo(
        page=page,
        per_page=per_page,
        total_items=len(active_sessions),
        total_pages=(len(active_sessions) + per_page - 1) // per_page,
        has_next=end_idx < len(active_sessions),
        has_prev=page > 1
    )
    
    return PaginatedResponse(
        data=paginated_sessions,
        pagination=pagination
    )


@router.post("/sessions", response_model=SessionInfo)
async def create_session(
    session_request: CreateSessionRequest,
    req: Request
) -> SessionInfo:
    """Create a new session."""
    
    session_manager: SessionManager = req.app.state.session_manager
    
    try:
        session_id = await session_manager.create_session(
            project_id=session_request.project_id,
            model=session_request.model,
            system_prompt=session_request.system_prompt
        )
        
        session_info = await session_manager.get_session(session_id)
        
        response = SessionInfo(
            id=session_info.session_id,
            project_id=session_info.project_id,
            title=session_request.title or f"Session {session_id[:8]}",
            model=session_info.model,
            system_prompt=session_info.system_prompt,
            created_at=session_info.created_at,
            updated_at=session_info.updated_at,
            is_active=session_info.is_active,
            total_tokens=session_info.total_tokens,
            total_cost=session_info.total_cost,
            message_count=session_info.message_count
        )
        
        logger.info(
            "Session created",
            session_id=session_id,
            project_id=session_request.project_id
        )
        
        return response
        
    except Exception as e:
        logger.error("Failed to create session", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "message": f"Failed to create session: {str(e)}",
                    "type": "internal_error",
                    "code": "session_creation_failed"
                }
            }
        )


@router.get("/sessions/stats")
async def get_session_stats(req: Request) -> Dict[str, Any]:
    """Get session statistics."""

    session_manager: SessionManager = req.app.state.session_manager
    claude_manager = req.app.state.claude_manager

    session_stats = session_manager.get_session_stats()
    active_claude_sessions = claude_manager.get_active_sessions()

    return {
        "session_stats": session_stats,
        "active_claude_sessions": len(active_claude_sessions),
        "claude_sessions": active_claude_sessions
    }


@router.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str, req: Request) -> SessionInfo:
    """Get session by ID."""
    
    session_manager: SessionManager = req.app.state.session_manager
    
    session_info = await session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "message": f"Session {session_id} not found",
                    "type": "not_found",
                    "code": "session_not_found"
                }
            }
        )
    
    return SessionInfo(
        id=session_info.session_id,
        project_id=session_info.project_id,
        title=f"Session {session_id[:8]}",
        model=session_info.model,
        system_prompt=session_info.system_prompt,
        created_at=session_info.created_at,
        updated_at=session_info.updated_at,
        is_active=session_info.is_active,
        total_tokens=session_info.total_tokens,
        total_cost=session_info.total_cost,
        message_count=session_info.message_count
    )


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, req: Request) -> JSONResponse:
    """Delete session by ID."""
    
    session_manager: SessionManager = req.app.state.session_manager
    claude_manager = req.app.state.claude_manager
    
    # Stop Claude process if running
    await claude_manager.stop_session(session_id)
    
    # End session
    await session_manager.end_session(session_id)
    
    logger.info("Session deleted", session_id=session_id)
    
    return JSONResponse(
        content={
            "session_id": session_id,
            "status": "deleted"
        }
    )
