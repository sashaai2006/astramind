from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.orchestrator import orchestrator
from backend.core.ws_manager import get_ws_manager

router = APIRouter()

@router.websocket("/ws/projects/{project_id}")
async def project_socket(websocket: WebSocket, project_id: str) -> None:
    await get_ws_manager().connect(project_id, websocket)
    # Send initial connection event in the same format as ProjectEvent
    from datetime import datetime, timezone
    await websocket.send_json({
        "type": "event",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "agent": "system",
        "level": "info",
        "msg": "WebSocket connected",
        "data": {}
    })
    try:
        while True:
            payload = await websocket.receive_text()
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if data.get("type") == "command" and data.get("command") == "stop":
                await orchestrator.request_stop(project_id)
                await websocket.send_json(
                    {"type": "info", "msg": "stop requested", "project_id": project_id}
                )
    except WebSocketDisconnect:
        await get_ws_manager().disconnect(project_id, websocket)

