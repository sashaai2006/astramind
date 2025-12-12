from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict


DocumentStatus = Literal["planning", "writing", "reviewing", "compiling", "done", "failed", "stopped"]


class DocumentState(TypedDict):
    document_id: str
    title: str
    description: str
    doc_type: str  # latex_article | latex_beamer
    agent_preset: Optional[str]
    custom_agent_id: Optional[str]
    team_id: Optional[str]
    persona_prompt: Optional[str]

    outline: str
    main_tex_path: str
    pdf_path: Optional[str]

    steps: List[Dict[str, Any]]
    status: DocumentStatus
    error: Optional[str]

