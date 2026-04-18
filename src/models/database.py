"""
Async SQLAlchemy database setup.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .orm import Base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://nwo:nwopass@localhost:5432/nwo_gallery",
)

engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("LOG_LEVEL", "INFO") == "DEBUG",
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def create_tables() -> None:
    """Create all tables (dev / test only — use Alembic in production)."""
    async with engine.begin() as conn:
        # Enable pgvector extension
        await conn.execute(
            __import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector")
        )
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """FastAPI dependency: yield an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
