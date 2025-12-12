from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Mapping, Set, List

from fastapi import WebSocket


class WSManager:
    """Track WebSocket connections per project."""

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

        # #region agent log
        with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
            import json as json_lib, time
            f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"ws_manager.py:31","message":"broadcast entry","data":{"project_id":project_id,"connections_count":len(connections),"msg":payload.get("msg","")[:50]},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion

        if not connections:
            # No connections - skip silently (project might not have active viewers)
            # #region agent log
            with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
                import json as json_lib, time
                f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"ws_manager.py:36","message":"broadcast no connections","data":{"project_id":project_id},"timestamp":int(time.time()*1000)}) + '\n')
            # #endregion
            return

        message = json.dumps(payload, default=str)

        async def _send(connection: WebSocket) -> WebSocket | None:
            try:
                # #region agent log
                with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
                    import json as json_lib, time
                    f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"ws_manager.py:42","message":"broadcast before send_text","data":{},"timestamp":int(time.time()*1000)}) + '\n')
                # #endregion
                # Avoid one slow client stalling broadcasts
                await asyncio.wait_for(connection.send_text(message), timeout=2.0)
                # #region agent log
                with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
                    import json as json_lib, time
                    f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"ws_manager.py:46","message":"broadcast after send_text success","data":{},"timestamp":int(time.time()*1000)}) + '\n')
                # #endregion
                return None
            except Exception as e:
                # #region agent log
                with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
                    import json as json_lib, time
                    f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"ws_manager.py:49","message":"broadcast send_text exception","data":{"exc_type":type(e).__name__,"exc_msg":str(e)[:200]},"timestamp":int(time.time()*1000)}) + '\n')
                # #endregion
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


ws_manager = WSManager()

