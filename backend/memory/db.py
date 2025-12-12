from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from backend.utils.logging import get_logger

from . import models

LOGGER = get_logger(__name__)
DATABASE_PATH = Path(__file__).resolve().parents[1] / "data.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DATABASE_PATH}"

from sqlalchemy.pool import AsyncAdaptedQueuePool

engine: AsyncEngine = create_async_engine(
    DATABASE_URL, 
    echo=False, 
    future=True, 
    connect_args={"check_same_thread": False},
    poolclass=AsyncAdaptedQueuePool,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
)

# OPTIMIZATION: Enable Write-Ahead Logging (WAL) for better concurrency
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

async_session_factory = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def init_db() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        # Lightweight schema migration for existing sqlite DBs (best effort)
        try:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN agent_preset VARCHAR"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN custom_agent_id VARCHAR"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN team_id VARCHAR"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE document_projects ADD COLUMN custom_agent_id VARCHAR"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE document_projects ADD COLUMN team_id VARCHAR"))
        except Exception:
            pass
    LOGGER.info("Database initialised at %s (WAL mode enabled)", DATABASE_PATH)

@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()

async def get_session_dependency() -> AsyncIterator[AsyncSession]:
    async with get_session() as session:
        yield session
