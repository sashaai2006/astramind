from __future__ import annotations
from typing import Optional
from backend.core.ws_manager import WSManager

_document_ws_manager: Optional[WSManager] = None

def get_document_ws_manager() -> WSManager:
    global _document_ws_manager
    if _document_ws_manager is None:
        _document_ws_manager = WSManager()
    return _document_ws_manager
