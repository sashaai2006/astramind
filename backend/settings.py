from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional, ClassVar

try:
    # Pydantic v2 (pydantic-settings)
    from pydantic_settings import BaseSettings  # type: ignore[import-not-found]
    from pydantic import Field
    PYDANTIC_V2 = True
except ImportError:
    # Pydantic v1 fallback
    from pydantic import BaseSettings, Field
    PYDANTIC_V2 = False

class Settings(BaseSettings):

    projects_root: Path = Field(default=Path(__file__).resolve().parents[1] / "projects")
    documents_root: Path = Field(default=Path(__file__).resolve().parents[1] / "documents")
    data_root: Path = Field(default=Path(__file__).resolve().parents[1] / "data")
    llm_mode: Literal["mock", "ollama", "groq", "github", "deepseek", "cerebras"] = Field(
        default="groq"
    )
    
    # Model configurations
    ollama_model: str = Field(default="llama3.2:3b")
    groq_model: str = Field(default="llama-3.3-70b-versatile")
    github_model: str = Field(default="gpt-4o")  # gpt-4o, claude-3-5-sonnet, llama-3.1-70b
    deepseek_model: str = Field(default="deepseek-chat")  # deepseek-chat or deepseek-coder
    cerebras_model: str = Field(default="llama-3.3-70b")  # llama-3.3-70b (best), llama3.1-8b, qwen-3-32b
    
    llm_semaphore: int = Field(default=1)  # Строго по одному запросу для стабильности на Groq
    github_api_url: str = Field(default="https://api.github.com")
    admin_api_key: Optional[str] = Field(default=None)

    # API Keys
    groq_api_key: Optional[str] = Field(default=None)
    openai_api_key: Optional[str] = Field(default=None)
    github_token: Optional[str] = Field(default=None)
    deepseek_api_key: Optional[str] = Field(default=None)
    cerebras_api_key: Optional[str] = Field(default=None)

    # Web search (ResearcherAgent)
    # Disabled by default to avoid blocking workflow startup
    enable_web_search: bool = Field(default=False)
    search_provider: Literal["duckduckgo", "google"] = Field(default="duckduckgo")
    google_search_api_key: Optional[str] = Field(default=None)
    google_search_engine_id: Optional[str] = Field(default=None)
    max_search_results: int = Field(default=5, ge=1, le=10)
    
    # Memory search (ProjectMemory)
    enable_memory_search: bool = Field(default=False)
    memory_search_max_results: int = Field(default=2, ge=1, le=5)
    memory_search_max_chars: int = Field(default=1000, ge=100, le=5000)

    # Ensure we load the project's root .env file even when the process
    # cwd is 'backend/' (e.g. when started via run_dev.py which sets cwd=backend).
    # Annotate as ClassVar so Pydantic doesn't treat it as a model field.
    root_env: ClassVar[str] = str(Path(__file__).resolve().parents[1] / ".env")

    # Pydantic v2 config (pydantic-settings)
    if PYDANTIC_V2:
        model_config = {
            "env_file": root_env,
            "env_file_encoding": "utf-8",
            "case_sensitive": False,
            "extra": "ignore",  # Allow extra env vars
        }
    else:
        class Config:  # type: ignore[dead-code]
            env_file = root_env
            env_file_encoding = "utf-8"
            case_sensitive = False
            extra = "ignore"

@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.projects_root.mkdir(parents=True, exist_ok=True)
    settings.documents_root.mkdir(parents=True, exist_ok=True)
    return settings
