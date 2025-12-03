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


class GitHubModelsAdapter(BaseLLMAdapter):
    """
    Adapter for GitHub Models API (FREE!)
    
    Available models:
    - gpt-4o (OpenAI)
    - gpt-4o-mini (OpenAI)
    - claude-3-5-sonnet (Anthropic)
    - llama-3.1-70b (Meta)
    - mistral-large (Mistral)
    
    Setup:
    1. Get token: https://github.com/settings/tokens (classic token with read:packages)
    2. Set GITHUB_TOKEN env var
    """

    def __init__(self, model: str = "gpt-4o"):
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            LOGGER.warning("GITHUB_TOKEN not found. GitHub Models adapter will fail.")
        
        # GitHub Models uses OpenAI-compatible API
        self.client = AsyncOpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=token,
        )
        self.model = model
        LOGGER.info("Initialized GitHub Models adapter with model: %s", model)

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
            LOGGER.error("GitHub Models request failed: %s", exc)
            raise

    async def _invoke(self, prompt: str, json_mode: bool) -> str:
        LOGGER.info("Calling GitHub Models with model '%s' (json_mode=%s)", self.model, json_mode)
        
        system_prompt = "You are a world-class software engineer with deep expertise in code generation."
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
            "temperature": 0.3,
            "max_tokens": 16000,
        }

        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self.client.chat.completions.create(**kwargs)
        
        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason == "length":
            LOGGER.error("GitHub Models response truncated due to token limit")
            raise RuntimeError("Response truncated (finish_reason=length)")

        content = choice.message.content
        LOGGER.info("GitHub Models response received (length=%d)", len(content or ""))
        return content or ""

