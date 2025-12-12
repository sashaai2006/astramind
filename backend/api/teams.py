from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field as PydanticField
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.presets import get_preset_by_id
from backend.memory.db import get_session_dependency
from backend.memory.models import CustomAgent, Team, TeamAgentLink, TeamMember

router = APIRouter(prefix="/api/teams", tags=["teams"])

class TeamCreate(BaseModel):
    name: str = PydanticField(min_length=1, max_length=80)
    description: str = PydanticField(default="", max_length=500)
    agent_ids: List[UUID] = PydanticField(default_factory=list, max_length=50)
    preset_ids: List[str] = PydanticField(default_factory=list, max_length=50)

class TeamUpdate(BaseModel):
    name: Optional[str] = PydanticField(default=None, min_length=1, max_length=80)
    description: Optional[str] = PydanticField(default=None, max_length=500)
    agent_ids: Optional[List[UUID]] = PydanticField(default=None, max_length=50)
    preset_ids: Optional[List[str]] = PydanticField(default=None, max_length=50)

class TeamOut(BaseModel):
    id: UUID
    name: str
    description: str
    agent_ids: List[UUID]
    preset_ids: List[str]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class TeamListResponse(BaseModel):
    teams: List[TeamOut]
    total: int
    limit: int
    offset: int

async def _ensure_agents_exist(session: AsyncSession, agent_ids: List[UUID]) -> None:
    if not agent_ids:
        return
    res = await session.execute(select(CustomAgent.id).where(CustomAgent.id.in_(agent_ids)))
    existing = {row[0] for row in res.all()}
    missing = [str(a) for a in agent_ids if a not in existing]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown agent_ids: {', '.join(missing[:10])}")

def _ensure_presets_exist(preset_ids: List[str]) -> None:
    if not preset_ids:
        return
    missing = [p for p in preset_ids if not get_preset_by_id(p)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown preset_ids: {', '.join(missing[:10])}")

async def _get_team_members(session: AsyncSession, team_id: UUID) -> tuple[List[UUID], List[str]]:
    # New table (supports custom + presets)
    res = await session.execute(select(TeamMember).where(TeamMember.team_id == team_id))
    members = list(res.scalars().all())

    agent_ids = {m.custom_agent_id for m in members if m.custom_agent_id}
    preset_ids = {m.preset_id for m in members if m.preset_id}

    # Backward-compat: old link table (custom agents only)
    res_old = await session.execute(select(TeamAgentLink.agent_id).where(TeamAgentLink.team_id == team_id))
    for row in res_old.all():
        agent_ids.add(row[0])

    return (sorted(agent_ids), sorted(preset_ids))  # type: ignore[arg-type]

@router.get("", response_model=TeamListResponse)
async def list_teams(
    session: AsyncSession = Depends(get_session_dependency),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
) -> TeamListResponse:
    q = select(Team)
    if search:
        like = f"%{search}%"
        q = q.where(Team.name.ilike(like))

    count_q = select(func.count()).select_from(q.subquery())
    res = await session.execute(count_q)
    total = int(res.scalar() or 0)

    q = q.order_by(Team.created_at.desc()).limit(limit).offset(offset)
    res = await session.execute(q)
    teams = list(res.scalars().all())

    out: List[TeamOut] = []
    for t in teams:
        agent_ids, preset_ids = await _get_team_members(session, t.id)
        out.append(
            TeamOut(
                id=t.id,
                name=t.name,
                description=t.description,
                agent_ids=agent_ids,
                preset_ids=preset_ids,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
        )

    return TeamListResponse(teams=out, total=total, limit=limit, offset=offset)

@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: TeamCreate,
    session: AsyncSession = Depends(get_session_dependency),
) -> TeamOut:
    await _ensure_agents_exist(session, payload.agent_ids)
    _ensure_presets_exist(payload.preset_ids)

    team = Team(name=payload.name, description=payload.description)
    session.add(team)
    await session.commit()
    await session.refresh(team)

    # Persist members in the new table (supports preset + custom)
    for agent_id in payload.agent_ids:
        session.add(TeamMember(team_id=team.id, custom_agent_id=agent_id))
    for preset_id in payload.preset_ids:
        session.add(TeamMember(team_id=team.id, preset_id=preset_id))
    await session.commit()

    agent_ids, preset_ids = await _get_team_members(session, team.id)
    return TeamOut(
        id=team.id,
        name=team.name,
        description=team.description,
        agent_ids=agent_ids,
        preset_ids=preset_ids,
        created_at=team.created_at,
        updated_at=team.updated_at,
    )

@router.get("/{team_id}", response_model=TeamOut)
async def get_team(
    team_id: UUID,
    session: AsyncSession = Depends(get_session_dependency),
) -> TeamOut:
    res = await session.execute(select(Team).where(Team.id == team_id))
    team = res.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    agent_ids, preset_ids = await _get_team_members(session, team.id)
    return TeamOut(
        id=team.id,
        name=team.name,
        description=team.description,
        agent_ids=agent_ids,
        preset_ids=preset_ids,
        created_at=team.created_at,
        updated_at=team.updated_at,
    )

@router.put("/{team_id}", response_model=TeamOut)
async def update_team(
    team_id: UUID,
    payload: TeamUpdate,
    session: AsyncSession = Depends(get_session_dependency),
) -> TeamOut:
    res = await session.execute(select(Team).where(Team.id == team_id))
    team = res.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    if payload.name is not None:
        team.name = payload.name
    if payload.description is not None:
        team.description = payload.description

    if payload.agent_ids is not None or payload.preset_ids is not None:
        agent_ids = payload.agent_ids if payload.agent_ids is not None else []
        preset_ids = payload.preset_ids if payload.preset_ids is not None else []

        await _ensure_agents_exist(session, agent_ids)
        _ensure_presets_exist(preset_ids)

        # Replace membership in new table
        res = await session.execute(select(TeamMember).where(TeamMember.team_id == team.id))
        members = list(res.scalars().all())
        for m in members:
            await session.delete(m)
        for agent_id in agent_ids:
            session.add(TeamMember(team_id=team.id, custom_agent_id=agent_id))
        for preset_id in preset_ids:
            session.add(TeamMember(team_id=team.id, preset_id=preset_id))

        # Also clear old link table to avoid confusion
        res_old = await session.execute(select(TeamAgentLink).where(TeamAgentLink.team_id == team.id))
        links = list(res_old.scalars().all())
        for link in links:
            await session.delete(link)

    session.add(team)
    await session.commit()
    await session.refresh(team)

    agent_ids, preset_ids = await _get_team_members(session, team.id)
    return TeamOut(
        id=team.id,
        name=team.name,
        description=team.description,
        agent_ids=agent_ids,
        preset_ids=preset_ids,
        created_at=team.created_at,
        updated_at=team.updated_at,
    )

@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: UUID,
    session: AsyncSession = Depends(get_session_dependency),
) -> None:
    res = await session.execute(select(Team).where(Team.id == team_id))
    team = res.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Delete members first (new table)
    res_m = await session.execute(select(TeamMember).where(TeamMember.team_id == team.id))
    members = list(res_m.scalars().all())
    for m in members:
        await session.delete(m)

    # Delete links first (old table, backward compat)
    res = await session.execute(select(TeamAgentLink).where(TeamAgentLink.team_id == team.id))
    links = list(res.scalars().all())
    for link in links:
        await session.delete(link)

    await session.delete(team)
    await session.commit()
    return None
