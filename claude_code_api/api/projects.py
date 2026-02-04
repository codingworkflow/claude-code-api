"""Projects API endpoint - Extension to OpenAI API."""

import math
import uuid

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from claude_code_api.core.claude_manager import (
    cleanup_project_directory,
    create_project_directory,
)
from claude_code_api.core.config import settings
from claude_code_api.core.database import db_manager
from claude_code_api.core.security import ensure_directory_within_base
from claude_code_api.models.openai import (
    CreateProjectRequest,
    PaginatedResponse,
    PaginationInfo,
    ProjectInfo,
)
from claude_code_api.utils.time import utc_now

logger = structlog.get_logger()
router = APIRouter()


@router.get("/projects", response_model=PaginatedResponse)
async def list_projects(
    page: int = 1, per_page: int = 20, req: Request = None
) -> PaginatedResponse:
    """List all projects."""
    page = max(1, page)
    per_page = max(1, per_page)
    total_items = await db_manager.count_projects()
    total_pages = math.ceil(total_items / per_page) if total_items else 0
    projects = await db_manager.list_projects(page, per_page)

    project_infos = [
        ProjectInfo(
            id=project.id,
            name=project.name,
            description=project.description,
            path=project.path,
            created_at=project.created_at,
            updated_at=project.updated_at,
            is_active=project.is_active,
        )
        for project in projects
    ]

    pagination = PaginationInfo(
        page=page,
        per_page=per_page,
        total_items=total_items,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )

    return PaginatedResponse(data=project_infos, pagination=pagination)


@router.post("/projects", response_model=ProjectInfo)
async def create_project(
    project_request: CreateProjectRequest, req: Request
) -> ProjectInfo:
    """Create a new project."""

    project_id = str(uuid.uuid4())

    # Create project directory
    if project_request.path:
        project_path = ensure_directory_within_base(
            project_request.path, settings.project_root
        )
    else:
        project_path = create_project_directory(project_id)

    # Create project in database
    project_data = {
        "id": project_id,
        "name": project_request.name,
        "description": project_request.description,
        "path": project_path,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "is_active": True,
    }

    try:
        await db_manager.create_project(project_data)

        project_info = ProjectInfo(**project_data)

        logger.info(
            "Project created",
            project_id=project_id,
            name=project_request.name,
            path=project_path,
        )

        return project_info

    except SQLAlchemyError as exc:
        logger.exception("Failed to create project")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "message": "Failed to create project.",
                    "type": "internal_error",
                    "code": "project_creation_failed",
                }
            },
        ) from exc


@router.get("/projects/{project_id}", response_model=ProjectInfo)
async def get_project(project_id: str, req: Request) -> ProjectInfo:
    """Get project by ID."""

    project = await db_manager.get_project(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "message": f"Project {project_id} not found",
                    "type": "not_found",
                    "code": "project_not_found",
                }
            },
        )

    return ProjectInfo(
        id=project.id,
        name=project.name,
        description=project.description,
        path=project.path,
        created_at=project.created_at,
        updated_at=project.updated_at,
        is_active=project.is_active,
    )


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, req: Request) -> JSONResponse:
    """Delete project by ID."""

    project = await db_manager.get_project(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "message": f"Project {project_id} not found",
                    "type": "not_found",
                    "code": "project_not_found",
                }
            },
        )

    deleted = await db_manager.delete_project(project_id)
    if deleted:
        cleanup_project_directory(project.path)

    logger.info("Project deleted", project_id=project_id)

    return JSONResponse(content={"project_id": project_id, "status": "deleted"})
