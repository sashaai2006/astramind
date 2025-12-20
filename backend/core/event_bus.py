from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from backend.core.ws_manager import get_ws_manager
from backend.memory.db import get_session
from backend.memory import utils as db_utils
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)

class ProjectEvent(BaseModel):
    type: str = Field(default="event")
    timestamp: str
    project_id: str
    agent: str
    level: str = Field(default="info")
    msg: str
    data: Dict[str, Any] = Field(default_factory=dict)

async def emit_event(
    project_id: str,
    msg: str,
    *,
    agent: str,
    level: str = "info",
    data: Optional[Dict[str, Any]] = None,
    persist: bool = True,
) -> None:
    payload = ProjectEvent(
        timestamp=datetime.now(timezone.utc).isoformat(),
        project_id=project_id,
        agent=agent,
        level=level,
        msg=msg,
        data=data or {},
    )

    # WS (best effort)
    try:
        payload_dict = payload.model_dump()
        LOGGER.debug("Broadcasting WS event for project %s: %s", project_id, payload_dict.get("msg", "")[:100])
        await get_ws_manager().broadcast(project_id, payload_dict)
    except Exception as e:
        LOGGER.exception("Failed to broadcast WS event for project %s: %s", project_id, e)

    # DB (fire and forget; do not block workflow on DB errors)
    if not persist:
        return

    async def _persist() -> None:
        try:
            async with get_session() as session:
                await db_utils.record_event(
                    session,
                    UUID(project_id),
                    msg,
                    agent=agent,
                    level=level,
                    data=data or {},
                )
        except Exception:
            LOGGER.exception("Failed to persist event for project %s", project_id)

    asyncio.create_task(_persist())

