from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from backend.core.document_ws_manager import document_ws_manager
from backend.memory.db import get_session
from backend.memory import utils as db_utils
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)


class DocumentEventPayload(BaseModel):
    type: str = Field(default="event")
    timestamp: str
    project_id: str  # Reuse frontend contract (LogPanel expects project_id)
    agent: str
    level: str = Field(default="info")
    msg: str
    data: Dict[str, Any] = Field(default_factory=dict)


async def emit_document_event(
    document_id: str,
    msg: str,
    *,
    agent: str,
    level: str = "info",
    data: Optional[Dict[str, Any]] = None,
    persist: bool = True,
) -> None:
    payload = DocumentEventPayload(
        timestamp=datetime.now(timezone.utc).isoformat(),
        project_id=document_id,
        agent=agent,
        level=level,
        msg=msg,
        data=data or {},
    )

    # WS best-effort
    try:
        await document_ws_manager.broadcast(document_id, payload.model_dump())
    except Exception:
        LOGGER.exception("Failed to broadcast document WS event for %s", document_id)

    if not persist:
        return

    async def _persist() -> None:
        try:
            async with get_session() as session:
                await db_utils.record_document_event(
                    session,
                    UUID(document_id),
                    msg,
                    agent=agent,
                    level=level,
                    data=data or {},
                )
        except Exception:
            LOGGER.exception("Failed to persist document event for %s", document_id)

    asyncio.create_task(_persist())

