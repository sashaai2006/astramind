from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


ProjectTarget = Literal["web", "api", "telegram"]
ProjectStatus = Literal["creating", "running", "stopped", "failed", "done"]

AgentPreset = str


class ProjectCreate(BaseModel):
    title: str
    description: str
    target: ProjectTarget
    agent_preset: Optional[AgentPreset] = None
    custom_agent_id: Optional[UUID] = None
    team_id: Optional[UUID] = None


class TaskStep(BaseModel):
    id: str
    name: str
    agent: str
    status: Literal["pending", "running", "failed", "done"]
    parallel_group: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class ArtifactInfo(BaseModel):
    path: str
    size_bytes: int


class ProjectStatusResponse(BaseModel):
    project_id: str
    status: ProjectStatus
    steps: List[TaskStep]
    artifacts: List[ArtifactInfo]


DocumentType = Literal["latex_article", "latex_beamer"]
DocumentStatus = Literal["creating", "running", "stopped", "failed", "done"]


class DocumentCreate(BaseModel):
    title: str
    description: str
    doc_type: DocumentType = "latex_article"
    agent_preset: Optional[AgentPreset] = None
    custom_agent_id: Optional[UUID] = None
    team_id: Optional[UUID] = None


class DocumentStatusResponse(BaseModel):
    document_id: str
    status: DocumentStatus
    artifacts: List[ArtifactInfo]


class FileEntry(BaseModel):
    path: str
    is_dir: bool
    size_bytes: int


class PublishRequest(BaseModel):
    token: str
    repo_name: str
    private: bool = True


class FileUpdate(BaseModel):
    path: str
    content: str


class EventPayload(BaseModel):
    type: str
    timestamp: datetime
    project_id: str
    agent: Optional[str] = None
    level: Literal["info", "error"] = "info"
    msg: str
    artifact_path: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


def safe_project_path(base: Path, project_id: str, relative_path: Optional[str]) -> Path:
    """Ensure the relative path stays within the project directory."""
    root = base / project_id
    if relative_path in (None, "", "/"):
        return root
    full = (root / relative_path).resolve()
    if not str(full).startswith(str(root.resolve())):
        raise ValueError("Path traversal detected")
    return full

