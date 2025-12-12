from typing import TypedDict, List, Dict, Any, Optional

class ProjectState(TypedDict):
    project_id: str
    title: str
    description: str
    target: str
    tech_stack: Optional[str]
    agent_preset: Optional[str]
    custom_agent_id: Optional[str]
    team_id: Optional[str]
    persona_prompt: Optional[str]
    # Web research integration
    research_results: Optional[Dict[str, Any]]  # cached web search results payload
    research_queries: List[str]  # history of performed queries
    plan: List[Dict[str, Any]]
    current_step_idx: int
    generated_files: List[Dict[str, str]]
    test_results: Optional[Dict[str, Any]]
    retry_count: int
    status: str  # planning, generating, testing, correcting, done, failed

