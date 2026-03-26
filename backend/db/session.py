"""
Async database session management.

Engine and session factory are created lazily to avoid import-time failures
when asyncpg is not installed (e.g., in test environments without a database).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from config import settings

# Lazy initialization — populated by init_db()
engine = None
async_session_factory = None


def init_db():
    """Initialize the database engine and session factory. Call during app startup."""
    global engine, async_session_factory

    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    engine = create_async_engine(
        settings.database_url,
        echo=not settings.is_production,
        pool_size=5,
        max_overflow=10,
    )

    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db() -> AsyncGenerator:
    """FastAPI dependency that yields an async database session."""
    if async_session_factory is None:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail="Database not available. Start PostgreSQL or run with docker-compose.",
        )
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
