"""Chat completions API endpoint - OpenAI compatible."""

import json
from typing import Any, Dict, Tuple

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from claude_code_api.core.claude_manager import create_project_directory
from claude_code_api.core.session_manager import SessionManager
from claude_code_api.models.claude import validate_claude_model
from claude_code_api.models.openai import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ErrorResponse,
)
from claude_code_api.utils.parser import (
    ClaudeOutputParser,
    OpenAIConverter,
    estimate_tokens,
    normalize_claude_message,
)
from claude_code_api.utils.streaming import (
    create_non_streaming_response,
    create_sse_response,
)

logger = structlog.get_logger()
router = APIRouter()

CHAT_COMPLETION_RESPONSES = {
    200: {
        "description": "Chat completion response (JSON when stream=false, SSE when stream=true).",
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/ChatCompletionResponse"}
            },
            "text/event-stream": {
                "schema": {"$ref": "#/components/schemas/ChatCompletionChunk"}
            },
        },
    },
    400: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


def _http_error(
    status_code: int, message: str, error_type: str, code: str
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"message": message, "type": error_type, "code": code}},
    )


async def _log_raw_request(req: Request) -> None:
    raw_body = await req.body()
    content_type = req.headers.get("content-type", "unknown")
    logger.info(
        "Raw request received",
        content_type=content_type,
        body_size=len(raw_body),
        user_agent=req.headers.get("user-agent", "unknown"),
        raw_body=raw_body.decode()[:1000] if raw_body else "empty",
    )


def _extract_prompts(request: ChatCompletionRequest) -> Tuple[str, str]:
    if not request.messages:
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            "At least one message is required",
            "invalid_request_error",
            "missing_messages",
        )
    user_messages = [msg for msg in request.messages if msg.role == "user"]
    if not user_messages:
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            "At least one user message is required",
            "invalid_request_error",
            "missing_user_message",
        )
    user_prompt = user_messages[-1].get_text_content()
    system_messages = [msg for msg in request.messages if msg.role == "system"]
    system_prompt = (
        system_messages[0].get_text_content()
        if system_messages
        else request.system_prompt
    )
    return user_prompt, system_prompt


async def _resolve_session(
    session_manager: SessionManager,
    request: ChatCompletionRequest,
    project_id: str,
    claude_model: str,
    system_prompt: str,
) -> str:
    if request.session_id:
        session_id = request.session_id
        session_info = await session_manager.get_session(session_id)
        if not session_info:
            raise _http_error(
                status.HTTP_404_NOT_FOUND,
                f"Session {session_id} not found",
                "invalid_request_error",
                "session_not_found",
            )
        return session_id
    return await session_manager.create_session(
        project_id=project_id, model=claude_model, system_prompt=system_prompt
    )


async def _collect_non_streaming_response(
    claude_process,
    session_manager: SessionManager,
    session_id: str,
    model: str,
    project_id: str,
) -> Dict[str, Any]:
    messages, parser = await _gather_claude_messages(claude_process)
    _log_message_summary(messages)

    usage_summary = OpenAIConverter.calculate_usage(parser)
    await _update_session_usage(
        session_manager, session_id, usage_summary, parser.total_cost
    )

    response = _build_non_streaming_response(
        messages, session_id, model, usage_summary, project_id
    )
    _log_response_payload(response)
    return response


async def _gather_claude_messages(claude_process) -> Tuple[list, ClaudeOutputParser]:
    messages = []
    parser = ClaudeOutputParser()
    async for claude_message in claude_process.get_output():
        _log_claude_message(claude_message)
        messages.append(claude_message)
        normalized = normalize_claude_message(claude_message)
        if not normalized:
            continue
        parser.parse_message(normalized)
        if parser.is_final_message(normalized):
            break
    return messages, parser


def _log_claude_message(claude_message: Any) -> None:
    logger.info(
        "Received Claude message",
        message_type=(
            claude_message.get("type")
            if isinstance(claude_message, dict)
            else type(claude_message).__name__
        ),
        message_keys=(
            list(claude_message.keys()) if isinstance(claude_message, dict) else []
        ),
        has_assistant_content=bool(
            isinstance(claude_message, dict)
            and claude_message.get("type") == "assistant"
            and claude_message.get("message", {}).get("content")
        ),
        message_preview=str(claude_message)[:200] if claude_message else "None",
    )


def _log_message_summary(messages: list) -> None:
    logger.info(
        "Claude messages collected",
        total_messages=len(messages),
        message_types=[
            msg.get("type") if isinstance(msg, dict) else type(msg).__name__
            for msg in messages
        ],
    )


async def _update_session_usage(
    session_manager: SessionManager,
    session_id: str,
    usage_summary: Dict[str, Any],
    total_cost: float,
) -> None:
    await session_manager.update_session(
        session_id=session_id,
        tokens_used=usage_summary.get("total_tokens", 0),
        cost=total_cost,
    )


def _build_non_streaming_response(
    messages: list,
    session_id: str,
    model: str,
    usage_summary: Dict[str, Any],
    project_id: str,
) -> Dict[str, Any]:
    response = create_non_streaming_response(
        messages=messages, session_id=session_id, model=model, usage=usage_summary
    )
    response["project_id"] = project_id
    return response


def _log_response_payload(response: Dict[str, Any]) -> None:
    choices = response.get("choices") or []
    first_choice = choices[0] if choices else {}
    message = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
    content = message.get("content") if isinstance(message, dict) else None

    logger.info(
        "Returning chat completion response",
        response_id=response.get("id"),
        choices_count=len(choices),
        has_choices_0=bool(choices),
        choices_0_keys=(
            list(first_choice.keys()) if isinstance(first_choice, dict) else []
        ),
        message_keys=list(message.keys()) if isinstance(message, dict) else [],
        content_length=len(content or ""),
        full_response_keys=list(response.keys()),
        response_size=len(str(response)),
    )


@router.post(
    "/chat/completions",
    response_model=ChatCompletionResponse,
    responses=CHAT_COMPLETION_RESPONSES,
)
async def create_chat_completion(request: ChatCompletionRequest, req: Request) -> Any:
    """Create a chat completion, compatible with OpenAI API."""

    # Log raw request for debugging
    try:
        await _log_raw_request(req)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to process request", error=str(e))
        raise _http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Internal server error",
            "internal_error",
            "internal_error",
        )

    # Get managers from app state
    session_manager: SessionManager = req.app.state.session_manager
    claude_manager = req.app.state.claude_manager

    # Extract client info for logging
    client_id = getattr(req.state, "client_id", "anonymous")

    logger.info(
        "Chat completion request validated",
        client_id=client_id,
        model=request.model,
        messages_count=len(request.messages),
        stream=request.stream,
        project_id=request.project_id,
        session_id=request.session_id,
    )

    try:
        # Validate model
        claude_model = validate_claude_model(request.model)

        user_prompt, system_prompt = _extract_prompts(request)

        # Handle project context
        project_id = request.project_id or f"default-{client_id}"
        project_path = create_project_directory(project_id)

        # Handle session management
        session_id = await _resolve_session(
            session_manager=session_manager,
            request=request,
            project_id=project_id,
            claude_model=claude_model,
            system_prompt=system_prompt,
        )

        # Start Claude Code process
        try:
            claude_process = await claude_manager.create_session(
                session_id=session_id,
                project_path=project_path,
                prompt=user_prompt,
                model=claude_model,
                system_prompt=system_prompt,
            )
        except Exception as e:
            logger.error(
                "Failed to create Claude session", session_id=session_id, error=str(e)
            )
            raise _http_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"Failed to start Claude Code: {str(e)}",
                "service_unavailable",
                "claude_unavailable",
            )

        # Use Claude's actual session ID
        claude_session_id = claude_process.session_id

        # Update session with user message
        await session_manager.update_session(
            session_id=claude_session_id,
            message_content=user_prompt,
            role="user",
            tokens_used=estimate_tokens(user_prompt),
        )

        # Handle streaming vs non-streaming
        if request.stream:
            return StreamingResponse(
                create_sse_response(claude_session_id, claude_model, claude_process),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "X-Session-ID": claude_session_id,
                    "X-Project-ID": project_id,
                },
            )

        return await _collect_non_streaming_response(
            claude_process=claude_process,
            session_manager=session_manager,
            session_id=claude_session_id,
            model=claude_model,
            project_id=project_id,
        )

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(
            "Unexpected error in chat completion",
            client_id=client_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "message": "Internal server error",
                    "type": "internal_error",
                    "code": "unexpected_error",
                }
            },
        )


@router.get("/chat/completions/{session_id}/status")
async def get_completion_status(session_id: str, req: Request) -> Dict[str, Any]:
    """Get status of a chat completion session."""

    session_manager: SessionManager = req.app.state.session_manager
    claude_manager = req.app.state.claude_manager

    # Get session info
    session_info = await session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "message": f"Session {session_id} not found",
                    "type": "not_found",
                    "code": "session_not_found",
                }
            },
        )

    # Get Claude process status
    claude_process = claude_manager.get_session(session_id)
    is_running = claude_process is not None and claude_process.is_running

    return {
        "session_id": session_id,
        "project_id": session_info.project_id,
        "model": session_info.model,
        "is_running": is_running,
        "created_at": session_info.created_at.isoformat(),
        "updated_at": session_info.updated_at.isoformat(),
        "total_tokens": session_info.total_tokens,
        "total_cost": session_info.total_cost,
        "message_count": session_info.message_count,
    }


@router.post("/chat/completions/debug")
async def debug_chat_completion(req: Request) -> Dict[str, Any]:
    """Debug endpoint to test request validation."""
    try:
        raw_body = await req.body()
        headers = dict(req.headers)

        logger.info(
            "Debug request",
            content_type=headers.get("content-type"),
            body_size=len(raw_body),
            headers=headers,
            raw_body=raw_body.decode() if raw_body else "empty",
        )

        if raw_body:
            json_data = json.loads(raw_body.decode())

            # Try validation
            try:
                request = ChatCompletionRequest(**json_data)
                return {
                    "status": "success",
                    "message": "Request validation passed",
                    "parsed_data": {
                        "model": request.model,
                        "messages_count": len(request.messages),
                        "stream": request.stream,
                    },
                }
            except ValidationError as e:
                return {
                    "status": "validation_error",
                    "message": str(e),
                    "errors": e.errors(),
                    "raw_data": json_data,
                }

        return {"status": "no_body"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.delete("/chat/completions/{session_id}")
async def stop_completion(session_id: str, req: Request) -> Dict[str, str]:
    """Stop a running chat completion session."""

    session_manager: SessionManager = req.app.state.session_manager
    claude_manager = req.app.state.claude_manager

    # Stop Claude process
    await claude_manager.stop_session(session_id)

    # End session
    session_manager.end_session(session_id)

    logger.info("Chat completion stopped", session_id=session_id)

    return {"session_id": session_id, "status": "stopped"}
