"""Chat completions API endpoint - OpenAI compatible."""

import hashlib
import json
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from claude_code_api.core.claude_manager import (
    ClaudeModelNotSupportedError,
    ClaudeSessionConflictError,
    create_project_directory,
)
from claude_code_api.core.session_manager import SessionManager
from claude_code_api.models.claude import get_default_model, validate_claude_model
from claude_code_api.models.openai import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ErrorResponse,
    ResponsesCreateRequest,
    ResponsesResponse,
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
from claude_code_api.utils.time import utc_timestamp

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

RESPONSES_API_RESPONSES = {
    200: {
        "model": ResponsesResponse,
        "description": "Responses API response (JSON when stream=false, SSE when stream=true).",
        "content": {
            "text/event-stream": {"schema": {"type": "string"}},
        },
    },
    400: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}

RESPONSE_TEXT_BLOCK_TYPES = {"input_text", "output_text", "text"}
RESPONSE_INPUT_ROLES = {"system", "user", "assistant", "tool"}


def _http_error(
    status_code: int, message: str, error_type: str, code: str
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"message": message, "type": error_type, "code": code}},
    )


def _input_error(message: str, code: str = "invalid_input") -> HTTPException:
    return _http_error(
        status.HTTP_400_BAD_REQUEST,
        message,
        "invalid_request_error",
        code,
    )


async def _log_raw_request(req: Request) -> None:
    raw_body = await req.body()
    content_type = req.headers.get("content-type", "unknown")
    sensitive_headers = {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "x-auth-token",
    }
    sanitized_headers = {}
    for key, value in req.headers.items():
        if key.lower() in sensitive_headers:
            sanitized_headers[key] = "<redacted>"
        else:
            sanitized_headers[key] = value
    body_hash = hashlib.sha256(raw_body).hexdigest() if raw_body else None
    logger.info(
        "Raw request received",
        content_type=content_type,
        body_size=len(raw_body),
        user_agent=sanitized_headers.get("user-agent", "unknown"),
        headers=sanitized_headers,
        body_hash=body_hash or "empty",
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


def _coerce_response_content_block(block: Any, location: str) -> str:
    if isinstance(block, str):
        return block

    if not isinstance(block, dict):
        raise _input_error(
            f"Unsupported content block at {location}: expected an object or string.",
            "unsupported_input_block",
        )

    block_type = block.get("type")
    if block_type in RESPONSE_TEXT_BLOCK_TYPES:
        if "text" not in block:
            raise _input_error(
                f"Text content block at {location} is missing the 'text' field.",
                "invalid_input_block",
            )
        return str(block["text"])

    if block_type is None:
        if "text" in block:
            return str(block["text"])
        if "content" in block:
            return str(block["content"])

    raise _input_error(
        f"Unsupported content block type at {location}: {block_type!r}.",
        "unsupported_input_block",
    )


def _coerce_response_content(content: Any, location: str) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = [
            _coerce_response_content_block(block, f"{location}.content[{index}]")
            for index, block in enumerate(content)
        ]
        return "\n".join(part for part in text_parts if part)
    if isinstance(content, dict):
        return _coerce_response_content_block(content, f"{location}.content")

    raise _input_error(
        f"Unsupported content at {location}: expected a string or content block array.",
        "unsupported_input_content",
    )


def _coerce_response_role(role: Any, location: str) -> str:
    if not isinstance(role, str) or not role:
        raise _input_error(
            f"Message at {location} is missing a valid 'role'.",
            "invalid_input_message",
        )

    if role == "developer":
        return "system"

    if role not in RESPONSE_INPUT_ROLES:
        raise _input_error(
            f"Unsupported message role at {location}: {role!r}.",
            "unsupported_input_role",
        )

    return role


def _responses_input_to_chat_messages(input_value: Any) -> List[Dict[str, Any]]:
    if isinstance(input_value, str):
        return [{"role": "user", "content": input_value}]

    if not isinstance(input_value, list):
        raise _input_error(
            "The 'input' field must be a string or an array of message objects.",
            "invalid_input",
        )

    messages: List[Dict[str, Any]] = []
    for index, item in enumerate(input_value):
        location = f"input[{index}]"
        if not isinstance(item, dict):
            raise _input_error(
                f"Message at {location} must be an object.",
                "invalid_input_message",
            )

        item_type = item.get("type")
        if item_type not in (None, "message"):
            raise _input_error(
                f"Unsupported input item type at {location}: {item_type!r}.",
                "unsupported_input_item",
            )

        role = _coerce_response_role(item.get("role"), location)
        content = _coerce_response_content(item.get("content"), location)
        message: Dict[str, Any] = {"role": role, "content": content}

        for optional_field in ("name", "tool_call_id", "tool_calls"):
            if optional_field in item:
                message[optional_field] = item[optional_field]

        messages.append(message)

    return messages


def _responses_request_to_chat_request(
    request: ResponsesCreateRequest, stream: bool = False
) -> ChatCompletionRequest:
    messages = _responses_input_to_chat_messages(request.input)
    system_prompt = request.instructions if request.instructions else None

    return ChatCompletionRequest(
        model=request.model,
        messages=messages,
        temperature=request.temperature,
        max_tokens=request.max_output_tokens,
        stream=stream,
        project_id=request.project_id,
        session_id=request.session_id,
        system_prompt=system_prompt,
    )


def _extract_chat_response_text(chat_response: Dict[str, Any]) -> str:
    choices = chat_response.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""

    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return str(content)


def _responses_usage_from_chat(chat_response: Dict[str, Any]) -> Dict[str, Any]:
    usage = chat_response.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}

    return {
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def _chat_response_to_responses_response(
    request: ResponsesCreateRequest, chat_response: Dict[str, Any]
) -> Dict[str, Any]:
    created_at = chat_response.get("created") or utc_timestamp()
    completed_at = utc_timestamp()
    output_text = _extract_chat_response_text(chat_response)

    return {
        "id": f"resp_{uuid.uuid4().hex}",
        "object": "response",
        "created_at": created_at,
        "status": "completed",
        "completed_at": completed_at,
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": request.max_output_tokens,
        "model": chat_response.get("model") or request.model,
        "output": [
            {
                "id": f"msg_{uuid.uuid4().hex}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": output_text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "output_text": output_text,
        "usage": _responses_usage_from_chat(chat_response),
    }


def _responses_stream_event(event_type: str, data: Dict[str, Any]) -> str:
    payload = {"type": event_type, **data}
    json_data = json.dumps(payload, separators=(",", ":"))
    return f"event: {event_type}\ndata: {json_data}\n\n"


def _responses_stream_error(message: str) -> str:
    return _responses_stream_event(
        "response.failed",
        {
            "response": {
                "id": f"resp_{uuid.uuid4().hex}",
                "object": "response",
                "created_at": utc_timestamp(),
                "status": "failed",
                "error": {
                    "message": message,
                    "type": "server_error",
                    "code": "stream_error",
                },
            }
        },
    )


async def _iter_sse_events(body_iterator: Any) -> AsyncGenerator[str, None]:
    buffer = ""
    async for chunk in body_iterator:
        if isinstance(chunk, bytes):
            buffer += chunk.decode("utf-8")
        else:
            buffer += str(chunk)

        while "\n\n" in buffer:
            raw_event, buffer = buffer.split("\n\n", 1)
            if raw_event.strip():
                yield raw_event

    if buffer.strip():
        yield buffer


def _sse_data(raw_event: str) -> Optional[str]:
    data_lines = []
    for line in raw_event.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    return "\n".join(data_lines)


def _responses_completed_payload(
    response_id: str,
    message_id: str,
    created_at: int,
    completed_at: int,
    request: ResponsesCreateRequest,
    model: str,
    output_text: str,
) -> Dict[str, Any]:
    return {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": "completed",
        "completed_at": completed_at,
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": request.max_output_tokens,
        "model": model,
        "output": [
            {
                "id": message_id,
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": output_text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "output_text": output_text,
        "usage": {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        },
    }


async def _create_responses_sse_from_chat_stream(
    chat_stream_response: StreamingResponse,
    request: ResponsesCreateRequest,
) -> AsyncGenerator[str, None]:
    response_id = f"resp_{uuid.uuid4().hex}"
    message_id = f"msg_{uuid.uuid4().hex}"
    created_at = utc_timestamp()
    model = request.model
    output_parts: List[str] = []
    content_started = False

    yield _responses_stream_event(
        "response.created",
        {
            "response": {
                "id": response_id,
                "object": "response",
                "created_at": created_at,
                "status": "in_progress",
                "model": model,
            }
        },
    )
    yield _responses_stream_event(
        "response.output_item.added",
        {
            "output_index": 0,
            "item": {
                "id": message_id,
                "type": "message",
                "status": "in_progress",
                "role": "assistant",
                "content": [],
            },
        },
    )

    try:
        async for raw_event in _iter_sse_events(chat_stream_response.body_iterator):
            payload = _sse_data(raw_event)
            if payload is None:
                continue
            if payload == "[DONE]":
                break

            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue

            if "error" in chunk:
                yield _responses_stream_event(
                    "response.failed", {"response": {"id": response_id, **chunk}}
                )
                return

            model = chunk.get("model") or model
            choices = chunk.get("choices") or []
            if not choices:
                continue

            choice = choices[0]
            delta = choice.get("delta") or {}
            text_delta = delta.get("content")
            if not text_delta:
                continue

            if not content_started:
                content_started = True
                yield _responses_stream_event(
                    "response.content_part.added",
                    {
                        "item_id": message_id,
                        "output_index": 0,
                        "content_index": 0,
                        "part": {
                            "type": "output_text",
                            "text": "",
                            "annotations": [],
                        },
                    },
                )

            output_parts.append(str(text_delta))
            yield _responses_stream_event(
                "response.output_text.delta",
                {
                    "item_id": message_id,
                    "output_index": 0,
                    "content_index": 0,
                    "delta": str(text_delta),
                },
            )

        output_text = "".join(output_parts)
        if not content_started:
            yield _responses_stream_event(
                "response.content_part.added",
                {
                    "item_id": message_id,
                    "output_index": 0,
                    "content_index": 0,
                    "part": {
                        "type": "output_text",
                        "text": "",
                        "annotations": [],
                    },
                },
            )

        yield _responses_stream_event(
            "response.output_text.done",
            {
                "item_id": message_id,
                "output_index": 0,
                "content_index": 0,
                "text": output_text,
            },
        )
        yield _responses_stream_event(
            "response.content_part.done",
            {
                "item_id": message_id,
                "output_index": 0,
                "content_index": 0,
                "part": {
                    "type": "output_text",
                    "text": output_text,
                    "annotations": [],
                },
            },
        )
        yield _responses_stream_event(
            "response.output_item.done",
            {
                "output_index": 0,
                "item": {
                    "id": message_id,
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": output_text,
                            "annotations": [],
                        }
                    ],
                },
            },
        )

        completed_at = utc_timestamp()
        yield _responses_stream_event(
            "response.completed",
            {
                "response": _responses_completed_payload(
                    response_id=response_id,
                    message_id=message_id,
                    created_at=created_at,
                    completed_at=completed_at,
                    request=request,
                    model=model,
                    output_text=output_text,
                )
            },
        )
        yield "data: [DONE]\n\n"

    except Exception as e:
        logger.error("Responses streaming error", error=str(e), exc_info=True)
        yield _responses_stream_error("Stream error")


async def _resolve_session(
    session_manager: SessionManager,
    request: ChatCompletionRequest,
    project_id: str,
    claude_model: Optional[str],
    system_prompt: Optional[str],
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
    "/responses",
    responses=RESPONSES_API_RESPONSES,
)
async def create_response(request: ResponsesCreateRequest, req: Request) -> Any:
    """Create a minimal OpenAI Responses API response."""
    logger.info(
        "Responses API request validated",
        model=request.model,
        stream=request.stream,
        max_output_tokens=request.max_output_tokens,
        project_id=request.project_id,
        session_id=request.session_id,
    )

    chat_request = _responses_request_to_chat_request(
        request, stream=bool(request.stream)
    )
    chat_response = await create_chat_completion(chat_request, req)

    if request.stream:
        if not isinstance(chat_response, StreamingResponse):
            raise _http_error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Unexpected chat completion streaming response type.",
                "internal_error",
                "unexpected_response_type",
            )
        return StreamingResponse(
            _create_responses_sse_from_chat_stream(chat_response, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    if hasattr(chat_response, "model_dump"):
        chat_response = chat_response.model_dump()

    if not isinstance(chat_response, dict):
        raise _http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Unexpected chat completion response type.",
            "internal_error",
            "unexpected_response_type",
        )

    return _chat_response_to_responses_response(request, chat_response)


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
        requested_model = (request.model or "").strip() or None
        # Normalize only when user explicitly requested a model.
        claude_model = (
            validate_claude_model(requested_model) if requested_model else None
        )
        response_model = claude_model or get_default_model()

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

            def _register_cli_session(cli_session_id: str):
                session_manager.register_cli_session(session_id, cli_session_id)

            claude_process = await claude_manager.create_session(
                session_id=session_id,
                project_path=project_path,
                prompt=user_prompt,
                model=claude_model,
                system_prompt=system_prompt,
                on_cli_session_id=_register_cli_session,
            )
        except ClaudeSessionConflictError as e:
            logger.warning(
                "Session already has an active Claude process",
                session_id=session_id,
                error=str(e),
            )
            raise _http_error(
                status.HTTP_409_CONFLICT,
                "The session is currently busy with another process.",
                "invalid_request_error",
                "session_busy",
            ) from e
        except ClaudeModelNotSupportedError as e:
            logger.warning(
                "Claude rejected requested model",
                session_id=session_id,
                model=claude_model,
                error=str(e),
            )
            raise _http_error(
                status.HTTP_400_BAD_REQUEST,
                "The requested model is not supported.",
                "invalid_request_error",
                "model_not_supported",
            ) from e
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
        api_session_id = session_id

        # Update session with user message
        await session_manager.update_session(
            session_id=api_session_id,
            message_content=user_prompt,
            role="user",
            tokens_used=estimate_tokens(user_prompt),
        )

        # Handle streaming vs non-streaming
        if request.stream:
            return StreamingResponse(
                create_sse_response(api_session_id, response_model, claude_process),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "X-Session-ID": api_session_id,
                    "X-Project-ID": project_id,
                },
            )

        return await _collect_non_streaming_response(
            claude_process=claude_process,
            session_manager=session_manager,
            session_id=api_session_id,
            model=response_model,
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
    await session_manager.end_session(session_id)

    logger.info("Chat completion stopped", session_id=session_id)

    return {"session_id": session_id, "status": "stopped"}
