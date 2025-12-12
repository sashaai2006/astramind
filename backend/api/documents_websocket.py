from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.document_ws_manager import document_ws_manager
from backend.core.document_orchestrator import document_orchestrator

router = APIRouter()


@router.websocket("/ws/documents/{document_id}")
async def document_socket(websocket: WebSocket, document_id: str) -> None:
    await document_ws_manager.connect(document_id, websocket)
    await websocket.send_json({"type": "info", "msg": "connected", "project_id": document_id})
    try:
        while True:
            payload = await websocket.receive_text()
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if data.get("type") == "command" and data.get("command") == "stop":
                await document_orchestrator.request_stop(document_id)
                await websocket.send_json({"type": "info", "msg": "stop requested", "project_id": document_id})
    except WebSocketDisconnect:
        await document_ws_manager.disconnect(document_id, websocket)

