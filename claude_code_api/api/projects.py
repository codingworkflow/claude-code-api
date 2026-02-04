"""Projects API endpoint - Extension to OpenAI API."""

import uuid
import os
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Request, HTTPException, status, Depends
from fastapi.responses import JSONResponse
import structlog

from claude_code_api.models.openai import (
    ProjectInfo, 
    CreateProjectRequest,
    PaginatedResponse,
    PaginationInfo
)
from claude_code_api.core.database import db_manager, Project
from claude_code_api.core.claude_manager import create_project_directory, cleanup_project_directory
from claude_code_api.core.security import validate_path
from claude_code_api.core.config import settings

logger = structlog.get_logger()
router = APIRouter()


@router.get("/projects", response_model=PaginatedResponse)
async def list_projects(
    page: int = 1,
    per_page: int = 20,
    req: Request = None
) -> PaginatedResponse:
    """List all projects."""
    
    # TODO: Implement proper pagination with database
    # For now, return mock data
    projects = [
        ProjectInfo(
            id="project-1",
            name="Sample Project",
            description="A sample project for testing",
            path="/tmp/claude_projects/project-1",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_active=True
        )
    ]
    
    pagination = PaginationInfo(
        page=page,
        per_page=per_page,
        total_items=len(projects),
        total_pages=1,
        has_next=False,
        has_prev=False
    )
    
    return PaginatedResponse(
        data=projects,
        pagination=pagination
    )


@router.post("/projects", response_model=ProjectInfo)
async def create_project(
    project_request: CreateProjectRequest,
    req: Request
) -> ProjectInfo:
    """Create a new project."""
    
    project_id = str(uuid.uuid4())
    
    # Create project directory
    if project_request.path:
        # Validate path
        project_path = validate_path(project_request.path, settings.project_root)

        os.makedirs(project_path, exist_ok=True)
    else:
        project_path = create_project_directory(project_id)
    
    # Create project in database
    project_data = {
        "id": project_id,
        "name": project_request.name,
        "description": project_request.description,
        "path": project_path,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "is_active": True
    }
    
    try:
        await db_manager.create_project(project_data)
        
        project_info = ProjectInfo(**project_data)
        
        logger.info(
            "Project created",
            project_id=project_id,
            name=project_request.name,
            path=project_path
        )
        
        return project_info
        
    except Exception as e:
        logger.error("Failed to create project", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "message": f"Failed to create project: {str(e)}",
                    "type": "internal_error",
                    "code": "project_creation_failed"
                }
            }
        )


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
                    "code": "project_not_found"
                }
            }
        )
    
    return ProjectInfo(
        id=project.id,
        name=project.name,
        description=project.description,
        path=project.path,
        created_at=project.created_at,
        updated_at=project.updated_at,
        is_active=project.is_active
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
                    "code": "project_not_found"
                }
            }
        )
    
    # TODO: Implement project deletion in database
    # cleanup_project_directory(project.path)
    
    logger.info("Project deleted", project_id=project_id)
    
    return JSONResponse(
        content={
            "project_id": project_id,
            "status": "deleted"
        }
    )
