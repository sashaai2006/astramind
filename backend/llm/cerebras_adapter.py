from __future__ import annotations

import os
from typing import Optional
import logging

from openai import AsyncOpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from backend.utils.logging import get_logger
from backend.llm.cache import get_cached, set_cached, get_cached_by_key, set_cached_by_key

from .adapter import BaseLLMAdapter

LOGGER = get_logger(__name__)


class CerebrasAdapter(BaseLLMAdapter):
    """
    Adapter for Cerebras Inference API (FASTEST in the world + FREE!)
    
    World's fastest AI inference (2000+ tokens/sec)
    Perfect for rapid prototyping and iteration
    
    Models:
    - llama3.1-8b
    - llama3.1-70b (recommended for quality)
    
    Setup:
    1. Get API key: https://cloud.cerebras.ai/
    2. Set CEREBRAS_API_KEY env var
    
    Free tier: Generous limits for development
    """

    def __init__(self, model: str = "llama3.1-70b"):
        api_key = os.getenv("CEREBRAS_API_KEY")
        if not api_key:
            LOGGER.warning("CEREBRAS_API_KEY not found. Cerebras adapter will fail.")
        
        # Cerebras uses OpenAI-compatible API
        self.client = AsyncOpenAI(
            base_url="https://api.cerebras.ai/v1",
            api_key=api_key,
        )
        self.model = model
        LOGGER.info("Initialized Cerebras adapter with model: %s (fastest inference)", model)

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(LOGGER, logging.INFO),
    )
    async def acomplete(self, prompt: str, json_mode: bool = False, cache_key: Optional[str] = None) -> str:
        # Check cache first
        cached = None
        if cache_key:
            cached = get_cached_by_key(cache_key)
        else:
            cached = get_cached(prompt, json_mode)
            
        if cached:
            LOGGER.info("Returning cached response")
            return cached
        
        try:
            result = await self._invoke(prompt, json_mode=json_mode)
            if cache_key:
                set_cached_by_key(cache_key, result)
            else:
                set_cached(prompt, result, json_mode)
            return result
        except Exception as exc:
            LOGGER.error("Cerebras request failed: %s", exc)
            raise

    async def _invoke(self, prompt: str, json_mode: bool) -> str:
        LOGGER.info("Calling Cerebras (FASTEST) with model '%s' (json_mode=%s)", self.model, json_mode)
        
        system_prompt = "You are an expert software engineer focused on writing clean, maintainable code."
        if json_mode:
            system_prompt += (
                " You MUST respond with ONLY valid JSON. "
                "Do NOT include any text, explanations, or markdown before or after the JSON object. "
                "Your entire response must be parseable by JSON.parse(). "
                "Start with { and end with }."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 8000,
        }

        # Cerebras doesn't support response_format yet, so we rely on prompt engineering for JSON

        response = await self.client.chat.completions.create(**kwargs)
        
        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason == "length":
            LOGGER.error("Cerebras response truncated due to token limit")
            raise RuntimeError("Response truncated (finish_reason=length)")

        content = choice.message.content
        LOGGER.info("Cerebras response received in RECORD TIME (length=%d)", len(content or ""))
        return content or ""

