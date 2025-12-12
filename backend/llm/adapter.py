from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from backend.settings import get_settings

class BaseLLMAdapter(ABC):
    @abstractmethod
    async def acomplete(self, prompt: str, json_mode: bool = False, cache_key: Optional[str] = None) -> str:

_cached_adapter: Optional[BaseLLMAdapter] = None

def get_llm_adapter() -> BaseLLMAdapter:
    global _cached_adapter
    if _cached_adapter:
        return _cached_adapter

    settings = get_settings()
    if settings.llm_mode == "mock":
        from .mock_adapter import MockLLMAdapter
        _cached_adapter = MockLLMAdapter()
    
    elif settings.llm_mode == "groq":
        from .groq_adapter import GroqLLMAdapter
        _cached_adapter = GroqLLMAdapter(model=settings.groq_model)
    
    elif settings.llm_mode == "github":
        from .github_adapter import GitHubModelsAdapter
        _cached_adapter = GitHubModelsAdapter(model=settings.github_model)
    
    elif settings.llm_mode == "deepseek":
        from .deepseek_adapter import DeepSeekAdapter
        _cached_adapter = DeepSeekAdapter(model=settings.deepseek_model)
    
    elif settings.llm_mode == "cerebras":
        from .cerebras_adapter import CerebrasAdapter
        _cached_adapter = CerebrasAdapter(model=settings.cerebras_model)
    
    else:  # ollama
        from .ollama_adapter import OllamaLLMAdapter
        _cached_adapter = OllamaLLMAdapter(model=settings.ollama_model)
    
    return _cached_adapter
