from __future__ import annotations

import hashlib
from typing import Dict, Optional
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)

# Simple in-memory cache (could be replaced with Redis for production)
_cache: Dict[str, str] = {}
_MAX_CACHE_SIZE = 100

def _make_key(prompt: str, json_mode: bool) -> str:
    content = f"{prompt}|json={json_mode}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]

def get_cached(prompt: str, json_mode: bool = False) -> Optional[str]:
    key = _make_key(prompt, json_mode)
    result = _cache.get(key)
    if result:
        LOGGER.info("Cache HIT for key %s", key)
    return result

def set_cached(prompt: str, response: str, json_mode: bool = False) -> None:
    key = _make_key(prompt, json_mode)
    _set_raw(key, response)

def get_cached_by_key(key: str) -> Optional[str]:
    result = _cache.get(key)
    if result:
        LOGGER.info("Cache HIT for explicit key %s", key)
    return result

def set_cached_by_key(key: str, response: str) -> None:
    _set_raw(key, response)

def _set_raw(key: str, response: str) -> None:
    # Evict oldest if cache is full (simple FIFO)
    if len(_cache) >= _MAX_CACHE_SIZE:
        oldest_key = next(iter(_cache))
        del _cache[oldest_key]
    
    _cache[key] = response
    LOGGER.info("Cache SET for key %s", key)

def clear_cache() -> None:
    _cache.clear()
    LOGGER.info("Cache cleared")
