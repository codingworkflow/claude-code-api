"""Server-Sent Events streaming utilities for OpenAI compatibility."""

import asyncio
import json
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import structlog

from claude_code_api.core.claude_manager import ClaudeProcess
from claude_code_api.utils.parser import (
    ClaudeOutputParser,
    OpenAIConverter,
    normalize_claude_message,
    tool_use_to_openai_call,
)
from claude_code_api.utils.time import utc_timestamp

logger = structlog.get_logger()

CHUNK_OBJECT_TYPE = "chat.completion.chunk"


class SSEFormatter:
    """Formats data for Server-Sent Events."""

    @staticmethod
    def format_event(data: Dict[str, Any]) -> str:
        """
        Emit a spec-compliant Server-Sent-Event chunk that works with
        EventSource / fetch-sse and the OpenAI client helpers.
        We deliberately omit the `event:` line so the default
        event-type **message** is used.
        """
        json_data = json.dumps(data, separators=(",", ":"))
        return f"data: {json_data}\n\n"

    @staticmethod
    def format_completion(data: str) -> str:
        """Format completion signal."""
        return "data: [DONE]\n\n"

    @staticmethod
    def format_error(error: str, error_type: str = "error") -> str:
        """Format error message."""
        error_data = {
            "error": {"message": error, "type": error_type, "code": "stream_error"}
        }
        return SSEFormatter.format_event(error_data)

    @staticmethod
    def format_heartbeat() -> str:
        """Format heartbeat ping."""
        return ": heartbeat\n\n"


class OpenAIStreamConverter:
    """Converts Claude Code output to OpenAI-compatible streaming format."""

    def __init__(self, model: str, session_id: str):
        self.model = model
        self.session_id = session_id
        self.completion_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"
        self.created = utc_timestamp()
        self.chunk_index = 0
        self.parser = ClaudeOutputParser()
        self.tool_call_index = 0

    def _build_chunk(
        self, delta: Dict[str, Any], finish_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        return {
            "id": self.completion_id,
            "object": CHUNK_OBJECT_TYPE,
            "created": self.created,
            "model": self.model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }

    def _build_tool_calls(self, tool_uses: List[Any]) -> List[Dict[str, Any]]:
        tool_calls = []
        for tool_use in tool_uses:
            call = tool_use_to_openai_call(tool_use)
            call["index"] = self.tool_call_index
            self.tool_call_index += 1
            tool_calls.append(call)
        return tool_calls

    def _assistant_chunks(self, message: Any) -> Tuple[List[str], bool, bool]:
        chunks: List[str] = []
        saw_text = False
        saw_tool_calls = False

        text_content = self.parser.extract_text_content(message).strip()
        if text_content:
            chunks.append(
                SSEFormatter.format_event(self._build_chunk({"content": text_content}))
            )
            saw_text = True

        tool_uses = self.parser.extract_tool_uses(message)
        if tool_uses:
            tool_calls = self._build_tool_calls(tool_uses)
            chunks.append(
                SSEFormatter.format_event(self._build_chunk({"tool_calls": tool_calls}))
            )
            saw_tool_calls = True

        return chunks, saw_text, saw_tool_calls

    async def convert_stream(
        self, claude_process: ClaudeProcess
    ) -> AsyncGenerator[str, None]:
        """Convert Claude Code output stream to OpenAI format."""
        try:
            # Send initial chunk to establish streaming
            yield SSEFormatter.format_event(
                self._build_chunk({"role": "assistant", "content": ""})
            )

            saw_assistant_text = False
            saw_tool_calls = False

            # Process Claude output
            async for claude_message in claude_process.get_output():
                message = normalize_claude_message(claude_message)
                if not message:
                    continue
                self.parser.parse_message(message)

                if self.parser.is_assistant_message(message):
                    chunks, saw_text, saw_tools = self._assistant_chunks(message)
                    for chunk in chunks:
                        yield chunk
                    saw_assistant_text = saw_assistant_text or saw_text
                    saw_tool_calls = saw_tool_calls or saw_tools

                if self.parser.is_final_message(message):
                    break

            # Send final chunk
            finish_reason = (
                "tool_calls" if (saw_tool_calls and not saw_assistant_text) else "stop"
            )
            yield SSEFormatter.format_event(
                self._build_chunk({}, finish_reason=finish_reason)
            )

            # Send completion signal
            yield SSEFormatter.format_completion("")

        except Exception as e:
            logger.error("Error in stream conversion", error=str(e))
            yield SSEFormatter.format_error(f"Stream error: {str(e)}")

    def get_final_response(self) -> Dict[str, Any]:
        """Get complete response in OpenAI format."""
        return {
            "id": self.completion_id,
            "object": "chat.completion",
            "created": self.created,
            "model": self.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Response completed"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "session_id": self.session_id,
        }


class StreamingManager:
    """Manages multiple streaming connections."""

    def __init__(self):
        self.active_streams: Dict[str, OpenAIStreamConverter] = {}
        self.heartbeat_interval = 30  # seconds

    async def create_stream(
        self, session_id: str, model: str, claude_process: ClaudeProcess
    ) -> AsyncGenerator[str, None]:
        """Create new streaming connection."""
        converter = OpenAIStreamConverter(model, session_id)
        self.active_streams[session_id] = converter

        try:
            # Start heartbeat task
            heartbeat_task = asyncio.create_task(self._send_heartbeats(session_id))

            # Stream conversion
            async for chunk in converter.convert_stream(claude_process):
                yield chunk

            # Cancel heartbeat
            heartbeat_task.cancel()

        except Exception as e:
            logger.error("Streaming error", session_id=session_id, error=str(e))
            yield SSEFormatter.format_error(f"Streaming failed: {str(e)}")
        finally:
            # Cleanup
            if session_id in self.active_streams:
                del self.active_streams[session_id]

    async def _send_heartbeats(self, session_id: str):
        """Send periodic heartbeats to keep connection alive."""
        while session_id in self.active_streams:
            await asyncio.sleep(self.heartbeat_interval)
            # Heartbeats are handled by the SSE client

    def get_active_stream_count(self) -> int:
        """Get number of active streams."""
        return len(self.active_streams)

    def cleanup_stream(self, session_id: str):
        """Cleanup specific stream."""
        if session_id in self.active_streams:
            del self.active_streams[session_id]

    def cleanup_all_streams(self):
        """Cleanup all streams."""
        self.active_streams.clear()


class ChunkBuffer:
    """Buffers chunks for smooth streaming."""

    def __init__(self, max_size: int = 1000):
        self.buffer = []
        self.max_size = max_size
        self.lock = asyncio.Lock()

    async def add_chunk(self, chunk: str):
        """Add chunk to buffer."""
        async with self.lock:
            self.buffer.append(chunk)
            if len(self.buffer) > self.max_size:
                self.buffer.pop(0)  # Remove oldest chunk

    async def get_chunks(self) -> AsyncGenerator[str, None]:
        """Get chunks from buffer."""
        while True:
            async with self.lock:
                if self.buffer:
                    chunk = self.buffer.pop(0)
                    yield chunk
                else:
                    await asyncio.sleep(0.01)  # Small delay to prevent busy waiting


class AdaptiveStreaming:
    """Adaptive streaming with backpressure handling."""

    def __init__(self):
        self.chunk_size = 1024
        self.min_chunk_size = 256
        self.max_chunk_size = 4096
        self.adjustment_factor = 1.1

    async def stream_with_backpressure(
        self,
        data_source: AsyncGenerator[str, None],
        client_ready_callback: Optional[callable] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream with adaptive chunk sizing based on client readiness."""
        buffer = ""

        async for data in data_source:
            buffer += data

            # Check if we have enough data to send
            while len(buffer) >= self.chunk_size:
                chunk = buffer[: self.chunk_size]
                buffer = buffer[self.chunk_size :]

                # Adjust chunk size based on client readiness
                if client_ready_callback and not client_ready_callback():
                    # Client is slow, reduce chunk size
                    self.chunk_size = max(
                        self.min_chunk_size,
                        int(self.chunk_size / self.adjustment_factor),
                    )
                else:
                    # Client is ready, can increase chunk size
                    self.chunk_size = min(
                        self.max_chunk_size,
                        int(self.chunk_size * self.adjustment_factor),
                    )

                yield chunk

        # Send remaining buffer
        if buffer:
            yield buffer


# Global streaming manager instance
streaming_manager = StreamingManager()


async def create_sse_response(
    session_id: str, model: str, claude_process: ClaudeProcess
) -> AsyncGenerator[str, None]:
    """Create SSE response for Claude Code output."""
    async for chunk in streaming_manager.create_stream(
        session_id, model, claude_process
    ):
        yield chunk


def _extract_assistant_payload(
    messages: list, parser: ClaudeOutputParser
) -> Tuple[List[str], List[Dict[str, Any]]]:
    tool_calls: List[Dict[str, Any]] = []
    content_parts: List[str] = []

    for i, msg in enumerate(messages):
        normalized = normalize_claude_message(msg)
        if not normalized:
            continue
        parser.parse_message(normalized)
        logger.info(
            "Processing message",
            message_index=i,
            msg_type=normalized.type,
            msg_keys=list(normalized.model_dump().keys()),
            is_assistant=parser.is_assistant_message(normalized),
        )

        if not parser.is_assistant_message(normalized):
            continue

        text_content = parser.extract_text_content(normalized).strip()
        logger.info(
            "Found assistant message",
            message_index=i,
            content_length=len(text_content),
            content_preview=text_content[:100] if text_content else "empty",
        )
        if text_content:
            content_parts.append(text_content)
            logger.info(
                "Extracted assistant text",
                message_index=i,
                content_preview=text_content[:50],
            )

        tool_uses = parser.extract_tool_uses(normalized)
        for tool_use in tool_uses:
            tool_calls.append(tool_use_to_openai_call(tool_use))

    return content_parts, tool_calls


def create_non_streaming_response(
    messages: list, session_id: str, model: str, usage: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Create non-streaming response."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"
    created = utc_timestamp()

    logger.info(
        "Creating non-streaming response",
        session_id=session_id,
        model=model,
        messages_count=len(messages),
        completion_id=completion_id,
    )

    parser = ClaudeOutputParser()
    content_parts, tool_calls = _extract_assistant_payload(messages, parser)

    # Use the actual content or fallback
    if content_parts:
        complete_content = "\n".join(content_parts).strip()
    else:
        complete_content = ""

    logger.info(
        "Final response content",
        content_parts_count=len(content_parts),
        final_content_length=len(complete_content),
        final_content_preview=complete_content[:100] if complete_content else "empty",
    )

    # Return simple OpenAI-compatible response with basic usage stats
    if usage is None:
        usage = OpenAIConverter.calculate_usage(parser)

    finish_reason = "tool_calls" if (tool_calls and not complete_content) else "stop"

    message_payload: Dict[str, Any] = {
        "role": "assistant",
        "content": complete_content or None,
    }
    if tool_calls:
        message_payload["tool_calls"] = tool_calls

    response = {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {"index": 0, "message": message_payload, "finish_reason": finish_reason}
        ],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
        "session_id": session_id,
    }

    logger.info(
        "Response created successfully",
        response_id=response["id"],
        choices_count=len(response["choices"]),
        message_content_length=len(response["choices"][0]["message"]["content"] or ""),
    )

    return response
