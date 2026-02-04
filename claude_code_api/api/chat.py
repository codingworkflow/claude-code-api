"""Chat completions API endpoint - OpenAI compatible."""

import json
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
import structlog

from claude_code_api.models.openai import (
    ChatCompletionRequest, 
    ChatCompletionResponse,
    ErrorResponse
)
from claude_code_api.models.claude import validate_claude_model
from claude_code_api.core.claude_manager import create_project_directory
from claude_code_api.core.session_manager import SessionManager
from claude_code_api.utils.streaming import create_sse_response, create_non_streaming_response
from claude_code_api.utils.parser import ClaudeOutputParser, OpenAIConverter, estimate_tokens, normalize_claude_message

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
            }
        }
    },
    400: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
    500: {"model": ErrorResponse}
}


@router.post(
    "/chat/completions",
    response_model=ChatCompletionResponse,
    responses=CHAT_COMPLETION_RESPONSES
)
async def create_chat_completion(
    request: ChatCompletionRequest,
    req: Request
) -> Any:
    """Create a chat completion, compatible with OpenAI API."""
    
    # Log raw request for debugging
    try:
        raw_body = await req.body()
        content_type = req.headers.get("content-type", "unknown")
        logger.info(
            "Raw request received",
            content_type=content_type,
            body_size=len(raw_body),
            user_agent=req.headers.get("user-agent", "unknown"),
            raw_body=raw_body.decode()[:1000] if raw_body else "empty"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to process request", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": {"message": "Internal server error", "type": "internal_error"}}
        )
    
    # Get managers from app state
    session_manager: SessionManager = req.app.state.session_manager
    claude_manager = req.app.state.claude_manager
    
    # Extract client info for logging
    client_id = getattr(req.state, 'client_id', 'anonymous')
    
    logger.info(
        "Chat completion request validated",
        client_id=client_id,
        model=request.model,
        messages_count=len(request.messages),
        stream=request.stream,
        project_id=request.project_id,
        session_id=request.session_id
    )
    
    try:
        # Validate model
        claude_model = validate_claude_model(request.model)
        
        # Validate message format
        if not request.messages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": {
                        "message": "At least one message is required",
                        "type": "invalid_request_error",
                        "code": "missing_messages"
                    }
                }
            )
        
        # Extract the user prompt (last user message)
        user_messages = [msg for msg in request.messages if msg.role == "user"]
        if not user_messages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": {
                        "message": "At least one user message is required",
                        "type": "invalid_request_error", 
                        "code": "missing_user_message"
                    }
                }
            )
        
        user_prompt = user_messages[-1].get_text_content()
        
        # Extract system prompt
        system_messages = [msg for msg in request.messages if msg.role == "system"]
        system_prompt = system_messages[0].get_text_content() if system_messages else request.system_prompt
        
        # Handle project context
        project_id = request.project_id or f"default-{client_id}"
        project_path = create_project_directory(project_id)
        
        # Handle session management
        if request.session_id:
            # Continue existing session
            session_id = request.session_id
            session_info = await session_manager.get_session(session_id)
            
            if not session_info:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "error": {
                            "message": f"Session {session_id} not found",
                            "type": "invalid_request_error",
                            "code": "session_not_found"
                        }
                    }
                )
        else:
            # Create new session
            session_id = await session_manager.create_session(
                project_id=project_id,
                model=claude_model,
                system_prompt=system_prompt
            )
        
        # Start Claude Code process
        try:
            claude_process = await claude_manager.create_session(
                session_id=session_id,
                project_path=project_path,
                prompt=user_prompt,
                model=claude_model,
                system_prompt=system_prompt,
                resume_session=request.session_id
            )
        except Exception as e:
            logger.error(
                "Failed to create Claude session",
                session_id=session_id,
                error=str(e)
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": {
                        "message": f"Failed to start Claude Code: {str(e)}",
                        "type": "service_unavailable",
                        "code": "claude_unavailable"
                    }
                }
            )
        
        # Use Claude's actual session ID
        claude_session_id = claude_process.session_id
        
        # Update session with user message
        await session_manager.update_session(
            session_id=claude_session_id,
            message_content=user_prompt,
            role="user",
            tokens_used=estimate_tokens(user_prompt)
        )
        
        # Handle streaming vs non-streaming
        if request.stream:
            # Return streaming response
            return StreamingResponse(
                create_sse_response(claude_session_id, claude_model, claude_process),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "X-Session-ID": claude_session_id,
                    "X-Project-ID": project_id
                }
            )
        else:
            # Collect all output for non-streaming response
            messages = []
            parser = ClaudeOutputParser()
            
            async for claude_message in claude_process.get_output():
                # Log each message from Claude
                logger.info(
                    "Received Claude message",
                    message_type=claude_message.get("type") if isinstance(claude_message, dict) else type(claude_message).__name__,
                    message_keys=list(claude_message.keys()) if isinstance(claude_message, dict) else [],
                    has_assistant_content=bool(isinstance(claude_message, dict) and 
                                             claude_message.get("type") == "assistant" and 
                                             claude_message.get("message", {}).get("content")),
                    message_preview=str(claude_message)[:200] if claude_message else "None"
                )
                
                messages.append(claude_message)
                normalized = normalize_claude_message(claude_message)
                if normalized:
                    parser.parse_message(normalized)
                    if parser.is_final_message(normalized):
                        break
            
            # Log what we collected
            logger.info(
                "Claude messages collected", 
                total_messages=len(messages),
                message_types=[msg.get("type") if isinstance(msg, dict) else type(msg).__name__ for msg in messages]
            )
            
            usage_summary = OpenAIConverter.calculate_usage(parser)
            await session_manager.update_session(
                session_id=claude_session_id,
                tokens_used=usage_summary.get("total_tokens", 0),
                cost=parser.total_cost
            )
            
            # Create non-streaming response
            response = create_non_streaming_response(
                messages=messages,
                session_id=claude_session_id,
                model=claude_model,
                usage=usage_summary
            )
            
            # Add extension fields
            response["project_id"] = project_id
            
            # Log the complete response before returning
            logger.info(
                "Returning chat completion response",
                response_id=response.get("id"),
                choices_count=len(response.get("choices", [])),
                has_choices_0=bool(response.get("choices") and len(response["choices"]) > 0),
                choices_0_keys=list(response["choices"][0].keys()) if response.get("choices") and len(response["choices"]) > 0 else [],
                message_keys=list(response["choices"][0]["message"].keys()) if response.get("choices") and len(response["choices"]) > 0 and "message" in response["choices"][0] else [],
                content_length=len((response["choices"][0]["message"].get("content") or "")) if response.get("choices") and len(response["choices"]) > 0 and "message" in response["choices"][0] else 0,
                full_response_keys=list(response.keys()),
                response_size=len(str(response))
            )
            
            return response
    
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(
            "Unexpected error in chat completion",
            client_id=client_id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "message": "Internal server error",
                    "type": "internal_error",
                    "code": "unexpected_error"
                }
            }
        )


@router.get("/chat/completions/{session_id}/status")
async def get_completion_status(
    session_id: str,
    req: Request
) -> Dict[str, Any]:
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
                    "code": "session_not_found"
                }
            }
        )
    
    # Get Claude process status
    claude_process = await claude_manager.get_session(session_id)
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
        "message_count": session_info.message_count
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
            raw_body=raw_body.decode() if raw_body else "empty"
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
                        "stream": request.stream
                    }
                }
            except ValidationError as e:
                return {
                    "status": "validation_error",
                    "message": str(e),
                    "errors": e.errors(),
                    "raw_data": json_data
                }
        
        return {"status": "no_body"}
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@router.delete("/chat/completions/{session_id}")
async def stop_completion(
    session_id: str,
    req: Request
) -> Dict[str, str]:
    """Stop a running chat completion session."""
    
    session_manager: SessionManager = req.app.state.session_manager
    claude_manager = req.app.state.claude_manager
    
    # Stop Claude process
    await claude_manager.stop_session(session_id)
    
    # End session
    await session_manager.end_session(session_id)
    
    logger.info("Chat completion stopped", session_id=session_id)
    
    return {
        "session_id": session_id,
        "status": "stopped"
    }
