"""Pydantic schemas for API requests and responses."""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from uuid import UUID

class FileEntry(BaseModel):
    """File entry in a project."""
    path: str
    is_dir: bool = False
    content: Optional[str] = None

class FileUpdate(BaseModel):
    """File update request."""
    path: str
    content: str

class ProjectCreate(BaseModel):
    """Project creation request."""
    title: str
    description: Optional[str] = None
    target: str
    agent_preset: Optional[str] = None
    custom_agent_id: Optional[str] = None
    team_id: Optional[str] = None

class ProjectStatusResponse(BaseModel):
    """Project status response."""
    id: str
    status: str
    version: int = 0
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)

class DocumentCreate(BaseModel):
    """Document creation request."""
    title: str
    doc_type: str
    description: Optional[str] = None
    agent_preset: Optional[str] = None
    custom_agent_id: Optional[str] = None
    team_id: Optional[str] = None

class ArtifactInfo(BaseModel):
    """Artifact information."""
    path: str
    content: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class DocumentStatusResponse(BaseModel):
    """Document status response."""
    document_id: str
    status: str
    name: Optional[str] = None
    doc_type: Optional[str] = None
    artifacts: List[ArtifactInfo] = Field(default_factory=list)

