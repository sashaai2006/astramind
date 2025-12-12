from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field as PydanticField
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.memory.db import get_session_dependency
from backend.memory.models import CustomAgent

router = APIRouter(prefix="/api/custom-agents", tags=["custom-agents"])

class CustomAgentCreate(BaseModel):
    name: str = PydanticField(min_length=1, max_length=80)
    prompt: str = PydanticField(min_length=1, max_length=20_000)
    tech_stack: List[str] = PydanticField(default_factory=list, max_length=50)

class CustomAgentUpdate(BaseModel):
    name: Optional[str] = PydanticField(default=None, min_length=1, max_length=80)
    prompt: Optional[str] = PydanticField(default=None, min_length=1, max_length=20_000)
    tech_stack: Optional[List[str]] = PydanticField(default=None, max_length=50)

class CustomAgentOut(BaseModel):
    id: UUID
    name: str
    prompt: str
    tech_stack: List[str]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class CustomAgentListResponse(BaseModel):
    agents: List[CustomAgentOut]
    total: int
    limit: int
    offset: int

@router.get("", response_model=CustomAgentListResponse)
async def list_custom_agents(
    session: AsyncSession = Depends(get_session_dependency),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
) -> CustomAgentListResponse:
    q = select(CustomAgent)
    if search:
        like = f"%{search}%"
        q = q.where(CustomAgent.name.ilike(like))

    count_q = select(func.count()).select_from(q.subquery())
    res = await session.execute(count_q)
    total = int(res.scalar() or 0)

    q = q.order_by(CustomAgent.created_at.desc()).limit(limit).offset(offset)
    res = await session.execute(q)
    agents = list(res.scalars().all())

    return CustomAgentListResponse(
        agents=[CustomAgentOut.model_validate(a, from_attributes=True) for a in agents],
        total=total,
        limit=limit,
        offset=offset,
    )

@router.post("", response_model=CustomAgentOut, status_code=status.HTTP_201_CREATED)
async def create_custom_agent(
    payload: CustomAgentCreate,
    session: AsyncSession = Depends(get_session_dependency),
) -> CustomAgentOut:
    agent = CustomAgent(name=payload.name, prompt=payload.prompt, tech_stack=payload.tech_stack)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return CustomAgentOut.model_validate(agent, from_attributes=True)

@router.get("/{agent_id}", response_model=CustomAgentOut)
async def get_custom_agent(
    agent_id: UUID,
    session: AsyncSession = Depends(get_session_dependency),
) -> CustomAgentOut:
    res = await session.execute(select(CustomAgent).where(CustomAgent.id == agent_id))
    agent = res.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Custom agent not found")
    return CustomAgentOut.model_validate(agent, from_attributes=True)

@router.put("/{agent_id}", response_model=CustomAgentOut)
async def update_custom_agent(
    agent_id: UUID,
    payload: CustomAgentUpdate,
    session: AsyncSession = Depends(get_session_dependency),
) -> CustomAgentOut:
    res = await session.execute(select(CustomAgent).where(CustomAgent.id == agent_id))
    agent = res.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Custom agent not found")

    if payload.name is not None:
        agent.name = payload.name
    if payload.prompt is not None:
        agent.prompt = payload.prompt
    if payload.tech_stack is not None:
        agent.tech_stack = payload.tech_stack

    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return CustomAgentOut.model_validate(agent, from_attributes=True)

@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_agent(
    agent_id: UUID,
    session: AsyncSession = Depends(get_session_dependency),
) -> None:
    res = await session.execute(select(CustomAgent).where(CustomAgent.id == agent_id))
    agent = res.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Custom agent not found")

    await session.delete(agent)
    await session.commit()
    return None
