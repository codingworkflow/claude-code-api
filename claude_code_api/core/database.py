"""Database models and connection management."""

from typing import AsyncGenerator, List, Optional

import structlog
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, relationship

from claude_code_api.models.claude import get_default_model
from claude_code_api.utils.time import utc_now

from .config import settings

logger = structlog.get_logger()

# Database setup
if settings.database_url.startswith("sqlite"):
    # Convert sync SQLite URL to async
    async_db_url = settings.database_url.replace("sqlite:///", "sqlite+aiosqlite:///")
else:
    async_db_url = settings.database_url

engine = create_async_engine(async_db_url, echo=settings.debug)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()


class Project(Base):
    """Project model."""

    __tablename__ = "projects"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    path = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    is_active = Column(Boolean, default=True)

    # Relationships
    sessions = relationship(
        "Session", back_populates="project", cascade="all, delete-orphan"
    )


class Session(Base):
    """Session model."""

    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    title = Column(String)
    model = Column(String, default=get_default_model)
    system_prompt = Column(Text)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    is_active = Column(Boolean, default=True)

    # Session metrics
    total_tokens = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)
    message_count = Column(Integer, default=0)

    # Relationships
    project = relationship("Project", back_populates="sessions")
    messages = relationship(
        "Message", back_populates="session", cascade="all, delete-orphan"
    )


class Message(Base):
    """Message model."""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    role = Column(String, nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    message_metadata = Column(Text)  # JSON metadata
    created_at = Column(DateTime, default=utc_now)

    # Token usage
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost = Column(Float, default=0.0)

    # Relationships
    session = relationship("Session", back_populates="messages")


class APIKey(Base):
    """API Key model for tracking usage."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_hash = Column(String, nullable=False, unique=True)
    name = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    last_used_at = Column(DateTime)

    # Usage tracking
    total_requests = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_tables():
    """Create database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")


async def close_database():
    """Close database connections."""
    await engine.dispose()
    logger.info("Database connections closed")


# Database utilities
class DatabaseManager:
    """Database operations manager."""

    @staticmethod
    async def get_project(project_id: str) -> Optional[Project]:
        """Get project by ID."""
        async with AsyncSessionLocal() as session:
            result = await session.get(Project, project_id)
            return result

    @staticmethod
    async def list_projects(page: int, per_page: int) -> List[Project]:
        """List projects with pagination."""
        page = max(1, page)
        per_page = max(1, min(per_page, 100))
        offset = (page - 1) * per_page
        async with AsyncSessionLocal() as session:
            stmt = (
                select(Project)
                .order_by(Project.created_at)
                .offset(offset)
                .limit(per_page)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    @staticmethod
    async def count_projects() -> int:
        """Count total projects."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(func.count(Project.id)))
            return int(result.scalar_one() or 0)

    @staticmethod
    async def create_project(project_data: dict) -> Project:
        """Create new project."""
        async with AsyncSessionLocal() as session:
            project = Project(**project_data)
            session.add(project)
            await session.commit()
            await session.refresh(project)
            return project

    @staticmethod
    async def delete_project(project_id: str) -> bool:
        """Delete project by ID."""
        async with AsyncSessionLocal() as session:
            project = await session.get(Project, project_id)
            if not project:
                return False
            await session.delete(project)
            await session.commit()
            return True

    @staticmethod
    async def get_session(session_id: str) -> Optional[Session]:
        """Get session by ID."""
        async with AsyncSessionLocal() as session:
            result = await session.get(Session, session_id)
            return result

    @staticmethod
    async def create_session(session_data: dict) -> Session:
        """Create new session."""
        async with AsyncSessionLocal() as session:
            session_obj = Session(**session_data)
            session.add(session_obj)
            await session.commit()
            await session.refresh(session_obj)
            return session_obj

    @staticmethod
    async def add_message(message_data: dict) -> Message:
        """Add message to session."""
        async with AsyncSessionLocal() as session:
            message = Message(**message_data)
            session.add(message)
            await session.commit()
            await session.refresh(message)
            return message

    @staticmethod
    async def update_session_metrics(session_id: str, tokens_used: int, cost: float):
        """Update session usage metrics."""
        async with AsyncSessionLocal() as session:
            stmt = (
                update(Session)
                .where(Session.id == session_id)
                .values(
                    total_tokens=Session.total_tokens + tokens_used,
                    total_cost=Session.total_cost + cost,
                    message_count=Session.message_count + 1,
                    updated_at=utc_now(),
                )
            )
            await session.execute(stmt)
            await session.commit()

    @staticmethod
    async def deactivate_session(session_id: str):
        """Mark session as inactive."""
        async with AsyncSessionLocal() as session:
            session_obj = await session.get(Session, session_id)
            if session_obj:
                session_obj.is_active = False
                session_obj.updated_at = utc_now()
                await session.commit()


# Create global database manager instance
db_manager = DatabaseManager()
