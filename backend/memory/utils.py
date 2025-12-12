from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Artifact,
    DocumentArtifact,
    DocumentEvent,
    DocumentProject,
    Event,
    Project,
    Task,
)

async def get_project(session: AsyncSession, project_id: UUID) -> Optional[Project]:
    result = await session.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one_or_none()

async def list_projects(session: AsyncSession) -> Sequence[Project]:
    result = await session.execute(select(Project))
    return result.scalars().all()

async def record_event(
    session: AsyncSession,
    project_id: UUID,
    message: str,
    *,
    agent: Optional[str] = None,
    level: str = "info",
    data: Optional[Dict[str, Any]] = None,
    commit: bool = True,
) -> Event:
    event = Event(
        project_id=project_id,
        agent=agent,
        level=level,
        message=message,
        data=data or {},
    )
    session.add(event)
    if commit:
        await session.commit()
        await session.refresh(event)
    return event

async def upsert_task(
    session: AsyncSession,
    *,
    project_id: UUID,
    task_id: UUID,
    name: str,
    agent: str,
    status: str,
    parallel_group: Optional[str],
    payload: Dict[str, Any],
    commit: bool = True,
) -> Task:
    result = await session.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task:
        task.status = status
        task.payload = payload
    else:
        task = Task(
            id=task_id,
            project_id=project_id,
            name=name,
            agent=agent,
            status=status,
            parallel_group=parallel_group,
            payload=payload,
        )
        session.add(task)
    
    if commit:
        await session.commit()
        await session.refresh(task)
    return task

async def update_task_and_record_event(
    session: AsyncSession,
    *,
    project_id: UUID,
    task_id: UUID,
    name: str,
    agent: str,
    status: str,
    parallel_group: Optional[str],
    payload: Dict[str, Any],
    event_message: str,
    event_level: str = "info",
) -> None:
    # Upsert Task (no commit)
    await upsert_task(
        session,
        project_id=project_id,
        task_id=task_id,
        name=name,
        agent=agent,
        status=status,
        parallel_group=parallel_group,
        payload=payload,
        commit=False
    )
    # Record Event (no commit)
    await record_event(
        session,
        project_id=project_id,
        message=event_message,
        agent=agent,
        level=event_level,
        commit=False
    )
    # Single commit for both
    await session.commit()

async def list_tasks(session: AsyncSession, project_id: UUID) -> List[Task]:
    result = await session.execute(select(Task).where(Task.project_id == project_id))
    return list(result.scalars().all())

async def add_artifacts(
    session: AsyncSession, project_id: UUID, paths: Iterable[str], sizes: Iterable[int]
) -> None:
    for path, size in zip(paths, sizes):
        artifact = Artifact(project_id=project_id, path=path, size_bytes=size)
        session.add(artifact)
    await session.commit()

async def list_artifacts(session: AsyncSession, project_id: UUID) -> List[Artifact]:
    result = await session.execute(
        select(Artifact).where(Artifact.project_id == project_id)
    )
    return list(result.scalars().all())

async def update_project_status(
    session: AsyncSession, project_id: UUID, status: str
) -> Project:
    await session.execute(
        update(Project).where(Project.id == project_id).values(status=status)
    )
    await session.commit()
    result = await session.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one()

async def get_document_project(session: AsyncSession, document_id: UUID) -> Optional[DocumentProject]:
    result = await session.execute(select(DocumentProject).where(DocumentProject.id == document_id))
    return result.scalar_one_or_none()

async def list_document_projects(session: AsyncSession, *, limit: int = 50, offset: int = 0) -> List[DocumentProject]:
    result = await session.execute(
        select(DocumentProject).order_by(DocumentProject.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())

async def update_document_status(session: AsyncSession, document_id: UUID, status: str) -> DocumentProject:
    await session.execute(
        update(DocumentProject).where(DocumentProject.id == document_id).values(status=status)
    )
    await session.commit()
    result = await session.execute(select(DocumentProject).where(DocumentProject.id == document_id))
    return result.scalar_one()

async def record_document_event(
    session: AsyncSession,
    document_id: UUID,
    message: str,
    *,
    agent: Optional[str] = None,
    level: str = "info",
    data: Optional[Dict[str, Any]] = None,
    commit: bool = True,
) -> DocumentEvent:
    event = DocumentEvent(
        document_id=document_id,
        agent=agent,
        level=level,
        message=message,
        data=data or {},
    )
    session.add(event)
    if commit:
        await session.commit()
        await session.refresh(event)
    return event

async def add_document_artifacts(
    session: AsyncSession, document_id: UUID, paths: Iterable[str], sizes: Iterable[int]
) -> None:
    for path, size in zip(paths, sizes):
        artifact = DocumentArtifact(document_id=document_id, path=path, size_bytes=size)
        session.add(artifact)
    await session.commit()

async def list_document_artifacts(session: AsyncSession, document_id: UUID) -> List[DocumentArtifact]:
    result = await session.execute(
        select(DocumentArtifact).where(DocumentArtifact.document_id == document_id)
    )
    return list(result.scalars().all())
