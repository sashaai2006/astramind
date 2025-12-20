from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Mapping, Set, List, Optional

from fastapi import WebSocket

class WSManager:

    def __init__(self) -> None:
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, project_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(project_id, set()).add(websocket)

    async def disconnect(self, project_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(project_id)
            if not conns:
                return
            conns.discard(websocket)
            if not conns:
                self._connections.pop(project_id, None)

    async def broadcast(self, project_id: str, payload: Mapping[str, Any]) -> None:
        async with self._lock:
            connections = list(self._connections.get(project_id, set()))

        if not connections:
            # No connections - skip silently (project might not have active viewers)
            return

        message = json.dumps(payload, default=str)

        async def _send(connection: WebSocket) -> WebSocket | None:
            try:
                # Avoid one slow client stalling broadcasts
                await asyncio.wait_for(connection.send_text(message), timeout=2.0)
                return None
            except Exception as e:
                # Log but don't fail the whole broadcast
                from backend.utils.logging import get_logger
                logger = get_logger(__name__)
                logger.debug("Failed to send WS message to client: %s", e)
                return connection

        dead_connections: List[WebSocket] = []
        if connections:
            results = await asyncio.gather(*(_send(c) for c in connections), return_exceptions=True)
            dead_connections = [c for c in results if c is not None and not isinstance(c, Exception)]
        
        # Clean up dead connections
        if dead_connections:
            async with self._lock:
                conns = self._connections.get(project_id)
                if conns:
                    for conn in dead_connections:
                        conns.discard(conn)

_ws_manager: Optional[WSManager] = None

def get_ws_manager() -> WSManager:
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WSManager()
    return _ws_manager
