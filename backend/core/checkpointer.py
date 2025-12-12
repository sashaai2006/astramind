from __future__ import annotations

import asyncio
import aiosqlite
from pathlib import Path
from typing import AsyncIterator
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)

_saver: AsyncSqliteSaver | None = None
_conn: aiosqlite.Connection | None = None

async def get_checkpointer() -> AsyncSqliteSaver:
    """Returns a singleton AsyncSqliteSaver instance."""
    global _saver, _conn
    
    if _saver is not None:
        return _saver
    
    db_path = Path(__file__).parent.parent / "data" / "langgraph_checkpoints.db"
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
    """Closes the checkpointer connection."""
    global _saver, _conn
    if _conn:
        await _conn.close()
        _conn = None
        _saver = None
        LOGGER.info("LangGraph checkpointer closed")

