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

    def __init__(self) -> None:
        self._compiled_graph = None
        self._init_lock = asyncio.Lock()
        self._stop_events: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        
    async def _get_graph(self):
        async with self._init_lock:
            if self._compiled_graph is None:
                try:
                    checkpointer = await asyncio.wait_for(get_checkpointer(), timeout=10.0)
                    self._compiled_graph = create_project_graph(checkpointer)
                except asyncio.TimeoutError:
                    LOGGER.error("Graph initialization timed out after 10s")
                    raise RuntimeError("Graph initialization timeout")
        return self._compiled_graph

    def get_stop_event(self, project_id: str) -> asyncio.Event:
        ev = self._stop_events.get(project_id)
        if ev is None:
            ev = asyncio.Event()
            self._stop_events[project_id] = ev
        return ev

    async def request_stop(self, project_id: str) -> None:
        self.get_stop_event(project_id).set()
        task = self._tasks.get(project_id)
        if task and not task.done():
            task.cancel()

    async def async_start(
        self, project_id: UUID, title: str, description: str, target: str
    ) -> None:
        project_str = str(project_id)
        LOGGER.info("Starting project %s via LangGraph", project_str)
        
        try:
            from backend.core.event_bus import emit_event
            from backend.llm.adapter import get_llm_adapter
            from backend.settings import get_settings
            
            settings = get_settings()
            LOGGER.info("LLM mode: %s", settings.llm_mode)
            
            try:
                adapter = get_llm_adapter()
                LOGGER.info("LLM adapter initialized: %s", type(adapter).__name__)
            except Exception as e:
                LOGGER.error("Failed to initialize LLM adapter: %s", e)
                await emit_event(project_str, f"LLM initialization failed: {str(e)}", agent="system", level="error")
                raise RuntimeError(f"LLM adapter initialization failed: {str(e)}")
            
            asyncio.create_task(
                emit_event(project_str, f"Starting project: {title}", agent="system", level="info")
            )

            agent_preset: Optional[str] = None
            custom_agent_id: Optional[str] = None
            team_id: Optional[str] = None
            persona_prompt: Optional[str] = None
            
            async def _load_agent_config():
                async with get_session() as session:
                    from sqlalchemy import select
                    project = await db_utils.get_project(session, project_id)
                    if project is not None:
                        agent_preset_val = getattr(project, "agent_preset", None)
                        custom_agent_id_val = str(getattr(project, "custom_agent_id", None)) if getattr(project, "custom_agent_id", None) else None
                        team_id_val = str(getattr(project, "team_id", None)) if getattr(project, "team_id", None) else None
                        persona_prompt_val: Optional[str] = None

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
                                res_members = await session.execute(
                                    select(TeamMember).where(TeamMember.team_id == team.id)
                                )
                                members = list(res_members.scalars().all())
                                custom_ids = {m.custom_agent_id for m in members if m.custom_agent_id}
                                preset_ids = {m.preset_id for m in members if m.preset_id}

                                res_links = await session.execute(
                                    select(TeamAgentLink.agent_id).where(TeamAgentLink.team_id == team.id)
                                )
                                for row in res_links.all():
                                    custom_ids.add(row[0])

                                members_prompt = ""
                                blocks = []

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
            
            try:
                agent_preset, custom_agent_id, team_id, persona_prompt = await asyncio.wait_for(
                    _load_agent_config(), 
                    timeout=0.15
                )
            except (asyncio.TimeoutError, Exception) as e:
                LOGGER.debug("Using default agent config: %s", e)

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
            
            task = asyncio.create_task(self._run_workflow(project_str, initial_state))
            self._tasks[project_str] = task
            task.add_done_callback(lambda _: self._tasks.pop(project_str, None))
        except Exception as e:
            LOGGER.exception("Failed to start project %s: %s", project_str, e)
            async with get_session() as session:
                await db_utils.update_project_status(session, project_id, "failed")
            raise

    async def _run_workflow(self, project_id: str, state: ProjectState = None):
        try:
            LOGGER.info("Getting graph for project %s", project_id)
            try:
                graph = await self._get_graph()
                LOGGER.info("Graph obtained successfully for project %s", project_id)
            except Exception as graph_error:
                LOGGER.exception("Failed to get graph for project %s: %s", project_id, graph_error)
                from backend.core.event_bus import emit_event
                await emit_event(project_id, f"Failed to initialize workflow: {str(graph_error)[:200]}", agent="system", level="error")
                async with get_session() as session:
                    await db_utils.update_project_status(session, UUID(project_id), "failed")
                return
            
            config = {"configurable": {"thread_id": project_id}}
            
            try:
                async with get_session() as session:
                    await db_utils.update_project_status(session, UUID(project_id), "running")
                LOGGER.info("Project status updated to 'running' for project %s", project_id)
            except Exception as status_error:
                LOGGER.warning("Failed to update project status to 'running' for project %s: %s", project_id, status_error)

            LOGGER.info("Invoking graph for project %s with state keys: %s", project_id, list(state.keys()) if state else "None")
            from backend.core.event_bus import emit_event
            await emit_event(project_id, "Starting workflow...", agent="system", level="info")
            
            try:
                LOGGER.info("Calling graph.ainvoke for project %s", project_id)
                result = await asyncio.wait_for(
                    graph.ainvoke(state, config=config),
                    timeout=600.0
                )
                LOGGER.info("graph.ainvoke completed for project %s, result keys: %s", project_id, list(result.keys()) if result else "None")
                
                final_status = result.get("status", "done")
                if final_status == "done":
                    LOGGER.info("Workflow completed successfully for project %s, updating status to 'done'", project_id)
                    async with get_session() as session:
                        await db_utils.update_project_status(session, UUID(project_id), "done")
                        await session.commit()
            except asyncio.TimeoutError:
                error_msg = "Workflow timed out after 600s"
                LOGGER.error("%s for project %s", error_msg, project_id)
                await emit_event(project_id, error_msg, agent="system", level="error")
                async with get_session() as session:
                    await db_utils.update_project_status(session, UUID(project_id), "failed")
                raise RuntimeError(error_msg)
            except Exception as invoke_error:
                LOGGER.exception("graph.ainvoke failed for project %s: %s", project_id, invoke_error)
                error_msg = f"Workflow execution failed: {str(invoke_error)[:200]}"
                await emit_event(project_id, error_msg, agent="system", level="error")
                async with get_session() as session:
                    await db_utils.update_project_status(session, UUID(project_id), "failed")
                raise
        except asyncio.CancelledError:
            LOGGER.info("Workflow cancelled for project %s", project_id)
            async with get_session() as session:
                await db_utils.update_project_status(session, UUID(project_id), "stopped")
            raise
        except Exception as e:
            LOGGER.exception("Workflow failed for project %s: %s", project_id, e)
            from backend.core.event_bus import emit_event
            await emit_event(project_id, f"Workflow error: {str(e)[:200]}", agent="system", level="error")
            async with get_session() as session:
                await db_utils.update_project_status(session, UUID(project_id), "failed")

    async def resume_project(self, project_id: UUID) -> None:
        project_str = str(project_id)
        LOGGER.info("Resuming project %s", project_str)
        
        try:
            graph = await self._get_graph()
            config = {"configurable": {"thread_id": project_str}}
            
            snapshot = await graph.aget_state(config)
            if not snapshot.values:
                LOGGER.warning("No checkpoint found for %s. Marking as failed.", project_str)
                async with get_session() as session:
                    await db_utils.update_project_status(session, project_id, "failed")
                return

            task = asyncio.create_task(self._run_workflow(project_str, state=None))
            self._tasks[project_str] = task
            task.add_done_callback(lambda _: self._tasks.pop(project_str, None))
        except Exception as e:
            LOGGER.error("Failed to resume project %s: %s", project_id, e)
            async with get_session() as session:
                await db_utils.update_project_status(session, project_id, "failed")

    async def shutdown(self) -> None:
        await close_checkpointer()

    def _group_steps(self, steps):
        from collections import OrderedDict
        from uuid import uuid4
        groups = OrderedDict()
        for step in steps:
            group_key = step.get("parallel_group") or step.get("id") or str(uuid4())
            groups.setdefault(group_key, []).append(step)
        return list(groups.items())

orchestrator = Orchestrator()
