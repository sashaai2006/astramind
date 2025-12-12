from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from backend.core.ws_manager import ws_manager
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
    """
    Single entry point for project events.

    - Sends WebSocket event to connected clients
    - Persists to DB (fire-and-forget) unless persist=False
    - Centralizes timestamp formatting + error handling
    """
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
        # #region agent log
        with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
            import json as json_lib, time
            f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"event_bus.py:56","message":"emit_event before broadcast","data":{"project_id":project_id,"msg":msg[:100],"agent":agent},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
        LOGGER.debug("Broadcasting WS event for project %s: %s", project_id, payload_dict.get("msg", "")[:100])
        await ws_manager.broadcast(project_id, payload_dict)
        # #region agent log
        with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
            import json as json_lib, time
            f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"event_bus.py:59","message":"emit_event after broadcast","data":{"project_id":project_id},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
    except Exception as e:
        # #region agent log
        with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
            import json as json_lib, time
            f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"event_bus.py:61","message":"emit_event broadcast exception","data":{"exc_type":type(e).__name__,"exc_msg":str(e)[:200]},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
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

