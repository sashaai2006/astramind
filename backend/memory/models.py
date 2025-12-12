from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlmodel import Column, DateTime, Field, JSON, SQLModel

class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    title: str
    description: str
    target: str
    status: str = Field(default="creating")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), default=datetime.utcnow)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
        )
    )
    agent_preset: Optional[str] = Field(default=None)
    custom_agent_id: Optional[UUID] = Field(default=None, foreign_key="custom_agents.id")
    team_id: Optional[UUID] = Field(default=None, foreign_key="teams.id")

class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    project_id: UUID = Field(foreign_key="projects.id", index=True)
    name: str
    agent: str
    status: str = Field(default="pending")
    parallel_group: Optional[str] = None
    payload: Dict[str, Any] = Field(
        sa_column=Column(JSON, default=dict, nullable=False)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), default=datetime.utcnow)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
        )
    )

class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    project_id: UUID = Field(foreign_key="projects.id", index=True)
    agent: Optional[str] = None
    level: str = Field(default="info")
    message: str
    data: Dict[str, Any] = Field(sa_column=Column(JSON, default=dict, nullable=False))
    timestamp: datetime = Field(
        sa_column=Column(DateTime(timezone=True), default=datetime.utcnow)
    )

class Artifact(SQLModel, table=True):
    __tablename__ = "artifacts"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    project_id: UUID = Field(foreign_key="projects.id", index=True)
    path: str
    size_bytes: int
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), default=datetime.utcnow)
    )

class DocumentProject(SQLModel, table=True):
    __tablename__ = "document_projects"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    title: str
    description: str
    doc_type: str = Field(default="latex_article")  # latex_article | latex_beamer | gost_explanatory_note | technical_assignment
    status: str = Field(default="creating")  # creating, running, stopped, failed, done
    agent_preset: Optional[str] = Field(default=None)
    custom_agent_id: Optional[UUID] = Field(default=None, foreign_key="custom_agents.id")
    team_id: Optional[UUID] = Field(default=None, foreign_key="teams.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), default=datetime.utcnow)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
        )
    )

class DocumentEvent(SQLModel, table=True):
    __tablename__ = "document_events"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    document_id: UUID = Field(foreign_key="document_projects.id", index=True)
    agent: Optional[str] = None
    level: str = Field(default="info")
    message: str
    data: Dict[str, Any] = Field(sa_column=Column(JSON, default=dict, nullable=False))
    timestamp: datetime = Field(
        sa_column=Column(DateTime(timezone=True), default=datetime.utcnow)
    )

class DocumentArtifact(SQLModel, table=True):
    __tablename__ = "document_artifacts"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    document_id: UUID = Field(foreign_key="document_projects.id", index=True)
    path: str
    size_bytes: int
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), default=datetime.utcnow)
    )

class CustomAgent(SQLModel, table=True):
    __tablename__ = "custom_agents"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    name: str = Field(index=True)
    prompt: str
    tech_stack: List[str] = Field(sa_column=Column(JSON, default=list, nullable=False))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), default=datetime.utcnow)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
        )
    )

class Team(SQLModel, table=True):
    __tablename__ = "teams"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    name: str = Field(index=True)
    description: str = Field(default="")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), default=datetime.utcnow)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
        )
    )

class TeamAgentLink(SQLModel, table=True):
    __tablename__ = "team_agent_links"

    team_id: UUID = Field(foreign_key="teams.id", primary_key=True)
    agent_id: UUID = Field(foreign_key="custom_agents.id", primary_key=True)

class TeamMember(SQLModel, table=True):

    __tablename__ = "team_members"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    team_id: UUID = Field(foreign_key="teams.id", index=True)
    custom_agent_id: Optional[UUID] = Field(default=None, foreign_key="custom_agents.id", index=True)
    preset_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), default=datetime.utcnow)
    )

