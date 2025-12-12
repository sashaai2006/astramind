from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.core.presets import (
    PRESETS,
    AgentPreset,
    get_popular_presets,
    get_preset_by_id,
    get_presets_by_category,
)

router = APIRouter(prefix="/api/presets", tags=["presets"])

class PresetListResponse(BaseModel):
    presets: List[AgentPreset]
    total: int

@router.get("", response_model=PresetListResponse)
async def list_presets(
    category: Optional[str] = Query(None, description="Filter by category"),
    popular_only: bool = Query(False, description="Only return popular presets"),
) -> PresetListResponse:
    if popular_only:
        presets = get_popular_presets()
    elif category:
        presets = get_presets_by_category(category)  # type: ignore[arg-type]
    else:
        presets = list(PRESETS)

    return PresetListResponse(presets=presets, total=len(presets))

@router.get("/{preset_id}", response_model=AgentPreset)
async def get_preset(preset_id: str) -> AgentPreset:
    preset = get_preset_by_id(preset_id)
    if not preset:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Preset not found")
    return preset
