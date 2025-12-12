from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
from uuid import UUID

from backend.core.state import ProjectState
from backend.core.graph import create_project_graph
from backend.core.checkpointer import get_checkpointer, close_checkpointer
from backend.memory.db import get_session
from backend.memory import utils as db_utils
from backend.core.presets import get_preset_by_id
from backend.memory.models import CustomAgent, Team, TeamAgentLink, TeamMember
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)


class Orchestrator:
    """Orchestrator using LangGraph for stateful workflow execution."""

    def __init__(self) -> None:
        self._compiled_graph = None
        self._init_lock = asyncio.Lock()
        self._stop_events: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        
    async def _get_graph(self):
        """Lazy initialization of the graph."""
        async with self._init_lock:
            if self._compiled_graph is None:
                # Add timeout to prevent hanging on checkpointer/graph creation
                try:
                    checkpointer = await asyncio.wait_for(get_checkpointer(), timeout=10.0)
                    self._compiled_graph = create_project_graph(checkpointer)
                except asyncio.TimeoutError:
                    LOGGER.error("Graph initialization timed out after 10s")
                    raise RuntimeError("Graph initialization timeout")
            return self._compiled_graph

    def get_stop_event(self, project_id: str) -> asyncio.Event:
        """Get (or create) the stop event for a project."""
        ev = self._stop_events.get(project_id)
        if ev is None:
            ev = asyncio.Event()
            self._stop_events[project_id] = ev
        return ev

    async def request_stop(self, project_id: str) -> None:
        """
        Request graceful stop of a running project.
        - Sets a stop flag checked by workflow nodes
        - Cancels the background task for faster interruption
        """
        self.get_stop_event(project_id).set()
        task = self._tasks.get(project_id)
        if task and not task.done():
            task.cancel()

    async def async_start(
        self, project_id: UUID, title: str, description: str, target: str
    ) -> None:
        """Start a new project workflow."""
        project_str = str(project_id)
        LOGGER.info("Starting project %s via LangGraph", project_str)
        
        # Emit initial event so frontend knows workflow started (non-blocking)
        from backend.core.event_bus import emit_event
        try:
            await asyncio.wait_for(emit_event(project_str, f"Starting project: {title}", agent="system", level="info"), timeout=1.0)
        except asyncio.TimeoutError:
            LOGGER.warning("Initial emit_event timed out, continuing...")

        # Initial state
        # Try to fetch agent config from DB (best effort, with timeout to avoid blocking)
        agent_preset: Optional[str] = None
        custom_agent_id: Optional[str] = None
        team_id: Optional[str] = None
        persona_prompt: Optional[str] = None
        
        async def _load_agent_config():
            async with get_session() as session:
                from sqlalchemy import select  # type: ignore[import-not-found]
                project = await db_utils.get_project(session, project_id)
                if project is not None:
                    agent_preset_val = getattr(project, "agent_preset", None)
                    custom_agent_id_val = str(getattr(project, "custom_agent_id", None)) if getattr(project, "custom_agent_id", None) else None
                    team_id_val = str(getattr(project, "team_id", None)) if getattr(project, "team_id", None) else None
                    persona_prompt_val: Optional[str] = None

                    # Resolve persona prompt for custom agent/team (highest priority)
                    if getattr(project, "custom_agent_id", None):
                        res = await session.execute(
                            select(CustomAgent).where(CustomAgent.id == project.custom_agent_id)
                        )
                        agent = res.scalar_one_or_none()
                        if agent:
                            tech = ", ".join(agent.tech_stack or [])
                            persona_prompt_val = (
                                f"=== CUSTOM AGENT: {agent.name} ===\n"
                                f"{agent.prompt}\n"
                                + (f"\nTech Stack: {tech}\n" if tech else "")
                            )
                    elif getattr(project, "team_id", None):
                        res = await session.execute(select(Team).where(Team.id == project.team_id))
                        team = res.scalar_one_or_none()
                        if team:
                            # New membership table (presets + custom)
                            res_members = await session.execute(
                                select(TeamMember).where(TeamMember.team_id == team.id)
                            )
                            members = list(res_members.scalars().all())

                            custom_ids = {m.custom_agent_id for m in members if m.custom_agent_id}
                            preset_ids = {m.preset_id for m in members if m.preset_id}

                            # Backward-compat: old link table (custom only)
                            res_links = await session.execute(
                                select(TeamAgentLink.agent_id).where(TeamAgentLink.team_id == team.id)
                            )
                            for row in res_links.all():
                                custom_ids.add(row[0])

                            members_prompt = ""
                            blocks = []

                            # Preset members
                            for pid in sorted(preset_ids):
                                preset = get_preset_by_id(pid)
                                if not preset:
                                    continue
                                tags = ", ".join(preset.tags or [])
                                blocks.append(
                                    f"--- PRESET: {preset.name} ({preset.id}) ---\n"
                                    f"{preset.persona_prompt}\n"
                                    + (f"\nTags: {tags}\n" if tags else "")
                                )

                            # Custom members
                            if custom_ids:
                                res_agents = await session.execute(
                                    select(CustomAgent).where(CustomAgent.id.in_(sorted(custom_ids)))
                                )
                                custom_members = list(res_agents.scalars().all())
                                for m in custom_members:
                                    tech = ", ".join(m.tech_stack or [])
                                    blocks.append(
                                        f"--- {m.name} ---\n{m.prompt}\n" + (f"\nTech Stack: {tech}\n" if tech else "")
                                    )
                            members_prompt = "\n\n".join(blocks)
                            persona_prompt_val = (
                                f"=== TEAM: {team.name} ===\n"
                                + (f"{team.description}\n\n" if team.description else "")
                                + (members_prompt if members_prompt else "No members.\n")
                            )
                    return agent_preset_val, custom_agent_id_val, team_id_val, persona_prompt_val
                return None, None, None, None
        
        # Load with timeout (3s max) - don't block startup
        try:
            agent_preset, custom_agent_id, team_id, persona_prompt = await asyncio.wait_for(_load_agent_config(), timeout=3.0)
        except asyncio.TimeoutError:
            LOGGER.warning("Agent config loading timed out, using defaults")
        except Exception as e:
            LOGGER.debug("Failed to load agent_preset for %s: %s", project_id, e)

        initial_state: ProjectState = {
            "project_id": project_str,
            "title": title,
            "description": description,
            "target": target,
            "tech_stack": None,
            "agent_preset": agent_preset,
            "custom_agent_id": custom_agent_id,
            "team_id": team_id,
            "persona_prompt": persona_prompt,
            "research_results": None,
            "research_queries": [],
            "plan": [],
            "current_step_idx": 0,
            "generated_files": [],
            "test_results": None,
            "retry_count": 0,
            "status": "planning"
        }

        # Fire and forget execution
        task = asyncio.create_task(self._run_workflow(project_str, initial_state))
        self._tasks[project_str] = task
        task.add_done_callback(lambda _: self._tasks.pop(project_str, None))

    async def _run_workflow(self, project_id: str, state: ProjectState = None):
        """Runs the LangGraph workflow."""
        try:
            graph = await self._get_graph()
            config = {"configurable": {"thread_id": project_id}}
            
            # Update DB status
            async with get_session() as session:
                await db_utils.update_project_status(session, UUID(project_id), "running")

            # Invoke graph
            # If state is None, it means we are resuming, passing None to input triggers load from checkpoint
            await graph.ainvoke(state, config=config)
        except asyncio.CancelledError:
            LOGGER.info("Workflow cancelled for project %s", project_id)
            async with get_session() as session:
                await db_utils.update_project_status(session, UUID(project_id), "stopped")
            raise
        except Exception as e:
            LOGGER.exception("Workflow failed for project %s: %s", project_id, e)
            async with get_session() as session:
                await db_utils.update_project_status(session, UUID(project_id), "failed")

    async def resume_project(self, project_id: UUID) -> None:
        """Resumes an interrupted project from checkpoint."""
        project_str = str(project_id)
        LOGGER.info("Resuming project %s", project_str)
        
        try:
            graph = await self._get_graph()
            config = {"configurable": {"thread_id": project_str}}
            
            # Check if we have a checkpoint
            snapshot = await graph.aget_state(config)
            if not snapshot.values:
                LOGGER.warning("No checkpoint found for %s (likely from pre-migration). Marking as failed.", project_str)
                # We could restart here, but without fetching project data from DB it's hard.
                # For now, just fail gracefully to stop the crash loop.
                async with get_session() as session:
                    await db_utils.update_project_status(session, project_id, "failed")
                return

            # Passing None as input to ainvoke with a thread_id will resume from last checkpoint
            task = asyncio.create_task(self._run_workflow(project_str, state=None))
            self._tasks[project_str] = task
            task.add_done_callback(lambda _: self._tasks.pop(project_str, None))
        except Exception as e:
            LOGGER.error("Failed to resume project %s: %s", project_id, e)
            async with get_session() as session:
                await db_utils.update_project_status(session, project_id, "failed")

    async def shutdown(self) -> None:
        """Cleanup resources."""
        await close_checkpointer()

    # Legacy method helper for group_steps used by generate_node
    # Can be moved to utils later
    def _group_steps(self, steps):
        from collections import OrderedDict
        from uuid import uuid4
        groups = OrderedDict()
        for step in steps:
            group_key = step.get("parallel_group") or step.get("id") or str(uuid4())
            groups.setdefault(group_key, []).append(step)
        return list(groups.items())


orchestrator = Orchestrator()
