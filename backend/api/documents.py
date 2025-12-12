from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.document_orchestrator import document_orchestrator
from backend.core.document_event_bus import emit_document_event
from backend.memory import utils as db_utils
from backend.memory.db import get_session_dependency
from backend.memory.models import DocumentProject
from backend.settings import get_settings
from backend.utils import fileutils
from backend.utils.logging import get_logger
from backend.utils.schemas import DocumentCreate, DocumentStatusResponse, FileEntry, FileUpdate, ArtifactInfo

LOGGER = get_logger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])

def _document_path(document_id: UUID) -> Path:
    settings = get_settings()
    return settings.documents_root / str(document_id)

@router.get("")
async def list_documents(
    session: AsyncSession = Depends(get_session_dependency),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    docs = await db_utils.list_document_projects(session, limit=limit, offset=offset)
    return {
        "documents": [
            {
                "id": str(d.id),
                "title": d.title,
                "description": d.description,
                "doc_type": d.doc_type,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ],
        "limit": limit,
        "offset": offset,
    }

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_document(
    payload: DocumentCreate, session: AsyncSession = Depends(get_session_dependency)
) -> dict:
    doc = DocumentProject(
        title=payload.title,
        description=payload.description,
        doc_type=payload.doc_type,
        status="creating",
        agent_preset=payload.agent_preset,
        custom_agent_id=payload.custom_agent_id,
        team_id=payload.team_id,
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    # Ensure dir + meta
    root = _document_path(doc.id)
    fileutils.ensure_project_dir(get_settings().documents_root, str(doc.id), {
        "title": payload.title,
        "description": payload.description,
        "doc_type": payload.doc_type,
        "agent_preset": payload.agent_preset,
        "custom_agent_id": str(payload.custom_agent_id) if payload.custom_agent_id else None,
        "team_id": str(payload.team_id) if payload.team_id else None,
    })

    await emit_document_event(str(doc.id), "Document created. Starting workflow...", agent="system")
    await document_orchestrator.async_start(
        doc.id,
        title=payload.title,
        description=payload.description,
        doc_type=payload.doc_type,
        agent_preset=payload.agent_preset,
        custom_agent_id=payload.custom_agent_id,
        team_id=payload.team_id,
    )

    return {"document_id": str(doc.id), "status": "created"}

@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: UUID, session: AsyncSession = Depends(get_session_dependency)
) -> DocumentStatusResponse:
    doc = await db_utils.get_document_project(session, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    artifacts = await db_utils.list_document_artifacts(session, document_id)
    return DocumentStatusResponse(
        document_id=str(doc.id),
        status=doc.status,  # type: ignore[arg-type]
        artifacts=[ArtifactInfo(path=a.path, size_bytes=a.size_bytes) for a in artifacts],
    )

@router.get("/{document_id}/files", response_model=List[FileEntry])
async def list_document_files(document_id: UUID) -> List[FileEntry]:
    root = _document_path(document_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    return fileutils.iter_file_entries(root)

@router.get("/{document_id}/file")
async def read_document_file(
    document_id: UUID,
    path: str = Query(...),
) -> Response:
    root = _document_path(document_id)
    try:
        data, is_text = fileutils.read_project_file(root, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    if is_text:
        return PlainTextResponse(data.decode("utf-8"))
    return Response(content=data, media_type="application/octet-stream", headers={"X-File": path})

@router.post("/{document_id}/file")
async def save_document_file(
    document_id: UUID,
    payload: FileUpdate,
    session: AsyncSession = Depends(get_session_dependency),
) -> dict:
    root = _document_path(document_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="Document not found")

    saved = fileutils.write_files(root.resolve(), [{"path": payload.path, "content": payload.content}])
    if not saved:
        raise HTTPException(status_code=400, detail="Invalid file path")

    target = saved[0]
    rel_path = target.relative_to(root.resolve()).as_posix()
    size = target.stat().st_size

    await db_utils.add_document_artifacts(session, document_id, [rel_path], [size])
    await db_utils.record_document_event(
        session,
        document_id,
        f"File {rel_path} saved",
        agent="editor",
        data={"artifact_path": rel_path, "size_bytes": size},
    )
    await emit_document_event(str(document_id), f"File {rel_path} saved", agent="editor", data={"artifact_path": rel_path}, persist=False)

    return {"path": rel_path, "size_bytes": size}

@router.get("/{document_id}/download")
async def download_pdf(document_id: UUID) -> FileResponse:
    root = _document_path(document_id)
    pdf = root / "main.pdf"
    if not pdf.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(pdf, media_type="application/pdf", filename=f"document_{document_id}.pdf")

