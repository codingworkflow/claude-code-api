"""Models API endpoint - OpenAI compatible."""

from datetime import datetime

import structlog
from fastapi import APIRouter, Request

from claude_code_api.models.claude import get_available_models
from claude_code_api.models.openai import ModelListResponse, ModelObject

logger = structlog.get_logger()
router = APIRouter()


@router.get("/models", response_model=ModelListResponse)
async def list_models(req: Request) -> ModelListResponse:
    """List available models, compatible with OpenAI API."""

    # Get Claude Code version for owned_by field
    claude_manager = req.app.state.claude_manager
    try:
        claude_version = await claude_manager.get_version()
        owned_by = f"anthropic-claude-{claude_version}"
    except Exception:
        owned_by = "anthropic"

    # Get available Claude models
    claude_models = get_available_models()

    # Convert to OpenAI format
    model_objects = []
    base_timestamp = int(datetime(2024, 1, 1).timestamp())

    for idx, model_info in enumerate(claude_models):
        model_obj = ModelObject(
            id=model_info.id,
            object="model",
            created=base_timestamp + idx,  # Stagger timestamps
            owned_by=owned_by,
        )
        model_objects.append(model_obj)

    # Only Claude models - no OpenAI aliases
    all_models = model_objects

    logger.info(
        "Listed models", count=len(all_models), claude_models=len(model_objects)
    )

    return ModelListResponse(object="list", data=all_models)


@router.get("/models/{model_id}")
async def get_model(model_id: str, req: Request) -> ModelObject:
    """Get specific model information."""

    # Get Claude Code version
    claude_manager = req.app.state.claude_manager
    try:
        claude_version = await claude_manager.get_version()
        owned_by = f"anthropic-claude-{claude_version}"
    except Exception:
        owned_by = "anthropic"

    # Check if it's a Claude model
    claude_models = get_available_models()
    for model_info in claude_models:
        if model_info.id == model_id:
            return ModelObject(
                id=model_info.id,
                object="model",
                created=int(datetime(2024, 1, 1).timestamp()),
                owned_by=owned_by,
            )

    # No OpenAI aliases supported

    # Model not found
    from fastapi import HTTPException, status

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error": {
                "message": f"Model {model_id} not found",
                "type": "not_found",
                "code": "model_not_found",
            }
        },
    )


@router.get("/models/capabilities")
async def get_model_capabilities():
    """Get detailed model capabilities (extension endpoint)."""

    claude_models = get_available_models()

    capabilities = []
    for model_info in claude_models:
        capability = {
            "id": model_info.id,
            "name": model_info.name,
            "description": model_info.description,
            "max_tokens": model_info.max_tokens,
            "supports_streaming": model_info.supports_streaming,
            "supports_tools": model_info.supports_tools,
            "pricing": {
                "input_cost_per_1k_tokens": model_info.input_cost_per_1k,
                "output_cost_per_1k_tokens": model_info.output_cost_per_1k,
                "currency": "USD",
            },
            "features": [
                "text_generation",
                "conversation",
                "code_generation",
                "analysis",
                "reasoning",
            ],
        }

        if model_info.supports_tools:
            capability["features"].extend(
                ["file_operations", "bash_execution", "project_management"]
            )

        capabilities.append(capability)

    return {
        "models": capabilities,
        "total": len(capabilities),
        "provider": "anthropic",
        "adapter": "claude-code-api",
    }
