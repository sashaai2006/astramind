import asyncio
from typing import Optional
from backend.settings import get_settings

_semaphore: Optional[asyncio.Semaphore] = None

def get_llm_semaphore() -> asyncio.Semaphore:
    """
    Get the global semaphore for LLM requests.
    This ensures we don't exceed the configured rate limit across the entire application.
    """
    global _semaphore
    if _semaphore is None:
        settings = get_settings()
        _semaphore = asyncio.Semaphore(settings.llm_semaphore)
    return _semaphore

