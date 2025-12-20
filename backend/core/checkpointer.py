from __future__ import annotations

import asyncio
import aiosqlite
from pathlib import Path
from typing import AsyncIterator
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)

if not hasattr(aiosqlite.Connection, 'is_alive'):
    def is_alive(self):
        try:
            return hasattr(self, '_connection') and self._connection is not None
        except (AttributeError, RuntimeError):
            return False
    
    aiosqlite.Connection.is_alive = is_alive

_saver: AsyncSqliteSaver | None = None
_conn: aiosqlite.Connection | None = None

async def get_checkpointer() -> AsyncSqliteSaver:
    global _saver, _conn
    
    # If we already have a saver and an active connection, reuse it.
    if _saver is not None and _conn is not None:
        try:
            if getattr(_conn, "is_alive", lambda: False)():
                return _saver
            else:
                LOGGER.warning("Existing checkpointer connection is not alive; reinitializing")
                # Attempt a clean close if possible
                try:
                    await _conn.close()
                except Exception:
                    pass
                _conn = None
                _saver = None
        except Exception:
            # Defensive: if anything goes wrong, reinitialize below
            _conn = None
            _saver = None
    
    from backend.settings import get_settings
    settings = get_settings()
    db_path = settings.data_root / "langgraph_checkpoints.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        LOGGER.info("Initializing LangGraph checkpointer at %s", db_path)
        # Add timeout to prevent hanging on DB initialization
        _conn = await asyncio.wait_for(aiosqlite.connect(str(db_path)), timeout=5.0)
        _saver = AsyncSqliteSaver(_conn)
        
        # Initialize tables (with timeout)
        await asyncio.wait_for(_saver.setup(), timeout=5.0)
        
        return _saver
    except asyncio.TimeoutError:
        LOGGER.error("Checkpointer initialization timed out after 5s")
        raise RuntimeError("Checkpointer initialization timeout")
    except Exception as e:
        LOGGER.error("Failed to initialize checkpointer: %s", e)
        raise

async def close_checkpointer():
    global _saver, _conn
    if _conn:
        await _conn.close()
        _conn = None
        _saver = None
        LOGGER.info("LangGraph checkpointer closed")

