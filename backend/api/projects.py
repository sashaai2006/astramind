from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.refactor import RefactorAgent
from backend.agents.reviewer import ReviewerAgent
from backend.core.orchestrator import orchestrator
from backend.core.event_bus import emit_event
from backend.memory import utils as db_utils
from backend.memory.db import get_session_dependency
from backend.memory.models import Project
from backend.memory.vector_store import get_project_memory, get_semantic_cache
from backend.memory.knowledge_sources import get_knowledge_registry, KnowledgeSource
from backend.settings import get_settings
from backend.utils import fileutils
from backend.utils.logging import get_logger
from backend.utils.schemas import (
    FileEntry,
    FileUpdate,
    ProjectCreate,
    ProjectStatusResponse,
)
from pydantic import BaseModel

router = APIRouter(prefix="/api/projects", tags=["projects"])
LOGGER = get_logger(__name__)
refactor_agent = RefactorAgent()
reviewer_agent = ReviewerAgent()

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, str]]] = None

class DeepReviewRequest(BaseModel):
    paths: List[str]  # List of file paths to review

def _project_path(project_id: UUID) -> Path:
    settings = get_settings()
    return settings.projects_root / str(project_id)

@router.get("")
async def list_projects(
    session: AsyncSession = Depends(get_session_dependency),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
) -> dict:
    from sqlalchemy import select, or_, func
    
    query = select(Project)
    
    # Search filter
    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            or_(
                Project.title.ilike(search_pattern),
                Project.description.ilike(search_pattern),
            )
        )
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    result = await session.execute(count_query)
    total = result.scalar() or 0
    
    # Apply pagination and ordering
    query = query.order_by(Project.created_at.desc()).limit(limit).offset(offset)
    
    result = await session.execute(query)
    projects = result.scalars().all()
    
    return {
        "projects": [
            {
                "id": str(p.id),
                "title": p.title,
                "description": p.description,
                "target": p.target,
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in projects
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate, session: AsyncSession = Depends(get_session_dependency)
) -> dict:
    project = Project(
        title=payload.title,
        description=payload.description,
        target=payload.target,
        status="creating",
        agent_preset=payload.agent_preset,
        custom_agent_id=payload.custom_agent_id,
        team_id=payload.team_id,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    settings = get_settings()
    fileutils.ensure_project_dir(
        settings.projects_root,
        str(project.id),
        {
            "title": payload.title,
            "description": payload.description,
            "target": payload.target,
        },
    )

    await orchestrator.async_start(
        project.id, payload.title, payload.description, payload.target
    )

    return {"project_id": str(project.id), "status": "created"}

@router.delete("/{project_id}")
async def delete_project(
    project_id: UUID, session: AsyncSession = Depends(get_session_dependency)
) -> dict:
    import shutil
    
    # Get project from DB
    project = await db_utils.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Delete project directory
    project_path = _project_path(project_id)
    if project_path.exists():
        try:
            shutil.rmtree(project_path)
            LOGGER.info("Deleted project directory: %s", project_path)
        except Exception as e:
            LOGGER.error("Failed to delete project directory %s: %s", project_path, e)
    
    # Delete from database
    await session.delete(project)
    await session.commit()
    
    LOGGER.info("Deleted project %s from database", project_id)
    
    return {"success": True, "message": f"Project {project.title} deleted"}

@router.get("/{project_id}/status", response_model=ProjectStatusResponse)
async def get_status(
    project_id: UUID, session: AsyncSession = Depends(get_session_dependency)
) -> ProjectStatusResponse:
    project = await db_utils.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    artifacts = await db_utils.list_artifacts(session, project_id)
    
    # Try to get steps from LangGraph state first
    steps = []
    try:
        from backend.core.orchestrator import orchestrator
        
        graph = await orchestrator._get_graph()
        config = {"configurable": {"thread_id": str(project_id)}}
        snapshot = await graph.aget_state(config)
        
        if snapshot.values and "plan" in snapshot.values:
            plan = snapshot.values.get("plan", [])
            current_idx = snapshot.values.get("current_step_idx", 0)
            project_status = snapshot.values.get("status", project.status)
            
            # Convert plan to steps format
            for idx, step_data in enumerate(plan):
                step_name = step_data.get("name", f"Step {idx + 1}")
                payload = step_data.get("payload", {})
                agent = payload.get("agent", "developer")
                parallel_group = step_data.get("parallel_group")
                
                # Determine step status based on current_idx
                if idx < current_idx:
                    step_status = "done"
                elif idx == current_idx and project_status in ["generating", "testing", "correcting"]:
                    step_status = "running"
                else:
                    step_status = "pending"
                
                steps.append({
                    "id": step_data.get("id", str(uuid4())),
                    "name": step_name,
                    "agent": agent,
                    "status": step_status,
                    "parallel_group": parallel_group,
                    "payload": payload,
                })
    except Exception as e:
        LOGGER.warning("Failed to read LangGraph state for project %s: %s. Falling back to tasks table.", project_id, e)
        # Fallback to tasks table for old projects
        tasks = await db_utils.list_tasks(session, project_id)
        steps = [
            {
                "id": str(task.id),
                "name": task.name,
                "agent": task.agent,
                "status": task.status,
                "parallel_group": task.parallel_group,
                "payload": task.payload,
            }
            for task in tasks
        ]
    
    return ProjectStatusResponse(
        project_id=str(project.id),
        status=project.status,  # type: ignore[arg-type]
        steps=steps,
        artifacts=[
            {
                "path": artifact.path,
                "size_bytes": artifact.size_bytes,
            }
            for artifact in artifacts
        ],
    )

@router.get("/{project_id}/files", response_model=List[FileEntry])
async def list_files(project_id: UUID) -> List[FileEntry]:
    project_path = _project_path(project_id)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    return fileutils.iter_file_entries(project_path)

@router.get("/{project_id}/file")
async def read_file(
    project_id: UUID,
    path: str = Query(...),
    version: Optional[int] = Query(default=None),
) -> Response:
    project_path = _project_path(project_id)
    full_path = project_path / path
    try:
        data, is_text = fileutils.read_project_file(project_path, path)
    except FileNotFoundError as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="File not found") from exc
    if is_text:
        return PlainTextResponse(data.decode("utf-8"))
    return Response(
        content=data, media_type="application/octet-stream", headers={"X-File": path}
    )

@router.post("/{project_id}/chat")
async def chat_with_project(project_id: UUID, payload: ChatRequest) -> dict:
    response = await refactor_agent.chat(project_id, payload.message, payload.history)
    return {"response": response}

@router.post("/{project_id}/review")
async def deep_review(project_id: UUID, payload: DeepReviewRequest) -> dict:
    project_path = _project_path(project_id)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Read file contents
    files_to_review = []
    for path in payload.paths:
        try:
            data, is_text = fileutils.read_project_file(project_path, path)
            if is_text:
                files_to_review.append({
                    "path": path,
                    "content": data.decode("utf-8")
                })
        except FileNotFoundError:
            continue
    
    if not files_to_review:
        raise HTTPException(status_code=400, detail="No valid files to review")
    
    # Broadcast that review is starting
    await emit_event(
        str(project_id),
        f"Deep review started for {len(files_to_review)} files...",
        agent="reviewer",
        data={"files_count": len(files_to_review)},
    )
    
    # Run review (parallel if multiple files)
    if len(files_to_review) == 1:
        result = await reviewer_agent.review(
            f"Review this file: {files_to_review[0]['path']}", 
            files_to_review
        )
    else:
        # Parallel review for multiple files
        tasks = [
            reviewer_agent.review(f"Review file: {f['path']}", [f])
            for f in files_to_review
        ]
        results = await asyncio.gather(*tasks)
        
        # Merge results
        all_comments = []
        all_approved = True
        for r in results:
            all_comments.extend(r.get("comments", []))
            if not r.get("approved", True):
                all_approved = False
        result = {"approved": all_approved, "comments": all_comments}
    
    # Broadcast result
    level = "info" if result.get("approved") else "warning"
    await emit_event(
        str(project_id),
        f"Review complete. Approved: {result.get('approved')}. Comments: {len(result.get('comments', []))}",
        agent="reviewer",
        level=level,
        data={"approved": bool(result.get("approved")), "comments_count": len(result.get("comments", []))},
    )
    
    return result

@router.get("/{project_id}/download")
async def download_project(
    project_id: UUID, version: Optional[int] = Query(default=None)
) -> FileResponse:
    project_path = _project_path(project_id)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    zip_path = fileutils.build_project_zip(project_path)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"project_{project_id}.zip",
    )

@router.get("/{project_id}/pdf")
async def download_project_pdf(project_id: UUID) -> FileResponse:
    import shutil
    from backend.sandbox.executor import execute_safe
    from backend.utils.logging import get_logger
    from backend.utils.markdown_to_latex import create_latex_document
    from backend.core.document_graph import _has_cyrillic
    
    LOGGER = get_logger(__name__)
    project_path = _project_path(project_id)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Find all Markdown files
    md_files = sorted(project_path.glob("*.md"))
    # Auto-migrate legacy .txt -> .md (user requirement: only md/latex)
    txt_files = sorted(project_path.glob("*.txt"))
    for txt in txt_files:
        try:
            md_target = txt.with_suffix(".md")
            if not md_target.exists():
                txt.rename(md_target)
            else:
                # If md already exists, keep md and delete txt to avoid confusion
                txt.unlink(missing_ok=True)
        except Exception:
            # Best effort; continue
            pass
    # Re-scan after migration
    md_files = sorted(project_path.glob("*.md"))
    if not md_files:
        raise HTTPException(status_code=404, detail="No Markdown files found in project")
    
    # Check if tectonic is available
    if not shutil.which("tectonic"):
        raise HTTPException(
            status_code=503,
            detail="tectonic is not installed. Please install it: brew install tectonic"
        )
    
    try:
        # Read all markdown files
        md_contents = []
        md_titles = []
        has_russian = False
        
        for md_file in md_files:
            content = md_file.read_text(encoding="utf-8")
            md_contents.append(content)
            md_titles.append(md_file.stem.replace('_', ' ').title())
            if not has_russian:
                has_russian = _has_cyrillic(content)
        
        # Generate LaTeX document
        LOGGER.info("Converting %d Markdown files to LaTeX for project %s", len(md_files), project_id)
        latex_doc = create_latex_document(md_contents, md_titles, has_russian=has_russian)
        
        # Write LaTeX file
        tex_path = project_path / "project.tex"
        tex_path.write_text(latex_doc, encoding="utf-8")
        LOGGER.info("LaTeX document written to %s", tex_path)
        
        # Compile with tectonic
        pdf_path = project_path / "project.pdf"
        LOGGER.info("Compiling LaTeX to PDF with tectonic...")
        
        tectonic_cmd = ["tectonic", "project.tex"]
        result = await execute_safe(
            tectonic_cmd,
            timeout_seconds=90,
            cwd=project_path
        )
        
        exit_code = result.get("exit_code", -1)
        stderr = str(result.get("stderr", ""))
        stdout = str(result.get("stdout", ""))
        
        if exit_code == 0 and pdf_path.exists():
            pdf_size = pdf_path.stat().st_size
            LOGGER.info("PDF generated successfully: %s (%d bytes)", pdf_path, pdf_size)
            return FileResponse(
                pdf_path,
                media_type="application/pdf",
                filename=f"project_{project_id}.pdf",
            )
        
        # Extract meaningful error from stderr
        error_lines = stderr.split('\n') if stderr else []
        error_summary = []
        for line in error_lines[-10:]:
            if 'error:' in line.lower() or 'fatal' in line.lower():
                error_summary.append(line.strip())
        
        error_msg = f"tectonic compilation failed (exit_code={exit_code})"
        if error_summary:
            error_msg += f": {'; '.join(error_summary[:3])}"
        elif stderr:
            error_msg += f": {stderr[:300]}"
        
        LOGGER.error("PDF generation failed: %s", error_msg)
        LOGGER.error("Full tectonic stderr: %s", stderr[:1000])
        LOGGER.error("Full tectonic stdout: %s", stdout[:1000])
        
        # Provide helpful error message
        if "font" in stderr.lower() or "fontspec" in stderr.lower():
            error_msg += ". Tried XeLaTeX and pdfLaTeX - both failed. Check tectonic installation and fonts."
        elif "package" in stderr.lower():
            error_msg += ". Missing LaTeX package - check tectonic installation."
        
        raise HTTPException(
            status_code=500,
            detail=f"PDF compilation failed: {error_msg}. LaTeX source saved at project.tex for debugging."
        )
            
    except HTTPException:
        raise
    except Exception as e:
        LOGGER.exception("Unexpected error during PDF generation: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate PDF: {str(e)[:200]}"
        )

@router.post("/{project_id}/file")
async def save_file(
    project_id: UUID,
    payload: FileUpdate,
    session: AsyncSession = Depends(get_session_dependency),
) -> dict:
    project_path = _project_path(project_id)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    # SAFE WRITE: prevent path traversal and writes outside project root
    project_root = project_path.resolve()
    saved = fileutils.write_files(project_root, [{"path": payload.path, "content": payload.content}])
    if not saved:
        raise HTTPException(status_code=400, detail="Invalid file path")

    target = saved[0]
    rel_path = target.relative_to(project_root).as_posix()
    size = target.stat().st_size

    await db_utils.add_artifacts(session, project_id, [rel_path], [size])
    await db_utils.record_event(
        session,
        project_id,
        f"File {rel_path} saved",
        agent="editor",
    )
    await emit_event(
        str(project_id),
        f"File {rel_path} saved",
        agent="editor",
        data={"artifact_path": rel_path, "size_bytes": size},
        persist=False,  # already recorded via db_utils.record_event above
    )
    return {"path": rel_path, "size_bytes": size}

# ============ Memory / Knowledge API ============

class MemorySearchRequest(BaseModel):
    query: str
    n_results: int = 5
    context_type: Optional[str] = None  # file, event, decision

class MemoryAddRequest(BaseModel):
    content: str
    context_type: str = "general"
    metadata: Optional[Dict[str, str]] = None

@router.get("/{project_id}/memory/search")
async def search_project_memory(
    project_id: UUID,
    query: str = Query(..., description="Search query"),
    n_results: int = Query(default=5, ge=1, le=20),
    context_type: Optional[str] = Query(default=None),
) -> List[Dict]:
    memory = get_project_memory(str(project_id))
    results = memory.search(query, n_results=n_results, context_type=context_type)
    return results

@router.post("/{project_id}/memory/add")
async def add_to_project_memory(
    project_id: UUID,
    request: MemoryAddRequest,
) -> Dict:
    memory = get_project_memory(str(project_id))
    success = memory.add_context(
        content=request.content,
        context_type=request.context_type,
        metadata=request.metadata
    )
    return {"success": success}

@router.get("/{project_id}/memory/context")
async def get_relevant_context(
    project_id: UUID,
    task: str = Query(..., description="Task description to find relevant context for"),
    max_chars: int = Query(default=3000, ge=100, le=10000),
) -> Dict:
    memory = get_project_memory(str(project_id))
    context = memory.get_relevant_context(task, max_chars=max_chars)
    return {"context": context, "length": len(context)}

@router.delete("/cache/clear")
async def clear_semantic_cache() -> Dict:
    cache = get_semantic_cache()
    success = cache.clear()
    return {"success": success, "message": "Semantic cache cleared" if success else "Failed to clear cache"}

# ============ Knowledge Sources API ============

class KnowledgeAddRequest(BaseModel):
    content: str
    title: str = ""
    tags: Optional[List[str]] = None

class KnowledgeSearchRequest(BaseModel):
    query: str
    n_results: int = 5
    source_ids: Optional[List[str]] = None
    tags: Optional[List[str]] = None

@router.get("/knowledge/sources")
async def list_knowledge_sources() -> List[Dict]:
    registry = get_knowledge_registry()
    sources = registry.list_sources()
    return [
        {
            "id": s.id,
            "name": s.name,
            "source_type": s.source_type,
            "description": s.description,
            "enabled": s.enabled,
        }
        for s in sources
    ]

@router.post("/knowledge/sources/{source_id}/add")
async def add_knowledge_to_source(
    source_id: str,
    request: KnowledgeAddRequest,
) -> Dict:
    registry = get_knowledge_registry()
    source = registry.get_source(source_id)
    
    if not source:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
    
    success = registry.add_knowledge(
        source_id=source_id,
        content=request.content,
        title=request.title,
        tags=request.tags
    )
    
    return {"success": success}

@router.post("/knowledge/search")
async def search_knowledge(request: KnowledgeSearchRequest) -> List[Dict]:
    registry = get_knowledge_registry()
    results = registry.search_knowledge(
        query=request.query,
        n_results=request.n_results,
        source_ids=request.source_ids,
        tags=request.tags
    )
    return results

@router.get("/knowledge/context")
async def get_knowledge_context(
    task: str = Query(..., description="Task description"),
    tech_stack: Optional[str] = Query(default=None, description="Technology stack (e.g., python, cpp, react)"),
    max_chars: int = Query(default=2000, ge=100, le=5000),
) -> Dict:
    registry = get_knowledge_registry()
    context = registry.get_context_for_task(
        task_description=task,
        tech_stack=tech_stack,
        max_chars=max_chars
    )
    return {"context": context, "length": len(context)}
