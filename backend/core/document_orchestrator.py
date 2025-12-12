from __future__ import annotations

import asyncio
from typing import Optional
from uuid import UUID

from backend.core.document_graph import create_document_graph
from backend.core.checkpointer import get_checkpointer, close_checkpointer
from backend.core.document_state import DocumentState
from backend.memory.db import get_session
from backend.memory import utils as db_utils
from backend.core.presets import get_preset_by_id
from backend.memory.models import CustomAgent, Team, TeamAgentLink, TeamMember
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)


class DocumentOrchestrator:
    def __init__(self) -> None:
        self._compiled_graph = None
        self._init_lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def _get_graph(self):
        async with self._init_lock:
            if self._compiled_graph is None:
                checkpointer = await get_checkpointer()
                self._compiled_graph = create_document_graph(checkpointer)
            return self._compiled_graph

    async def async_start(
        self,
        document_id: UUID,
        *,
        title: str,
        description: str,
        doc_type: str,
        agent_preset: Optional[str] = None,
        custom_agent_id: Optional[UUID] = None,
        team_id: Optional[UUID] = None,
    ) -> None:
        doc_str = str(document_id)

        persona_prompt: Optional[str] = None
        if custom_agent_id or team_id:
            try:
                async with get_session() as session:
                    from sqlalchemy import select  # type: ignore[import-not-found]
                    if custom_agent_id:
                        res = await session.execute(select(CustomAgent).where(CustomAgent.id == custom_agent_id))
                        agent = res.scalar_one_or_none()
                        if agent:
                            tech = ", ".join(agent.tech_stack or [])
                            persona_prompt = (
                                f"=== CUSTOM AGENT: {agent.name} ===\n"
                                f"{agent.prompt}\n"
                                + (f"\nTech Stack: {tech}\n" if tech else "")
                            )
                    elif team_id:
                        res = await session.execute(select(Team).where(Team.id == team_id))
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
                                        f"--- {m.name} ---\n{m.prompt}\n"
                                        + (f"\nTech Stack: {tech}\n" if tech else "")
                                    )

                            members_prompt = "\n\n".join(blocks)
                            persona_prompt = (
                                f"=== TEAM: {team.name} ===\n"
                                + (f"{team.description}\n\n" if team.description else "")
                                + (members_prompt if members_prompt else "No members.\n")
                            )
            except Exception:
                LOGGER.debug("Failed to resolve persona prompt for document %s", doc_str)

        initial_state: DocumentState = {
            "document_id": doc_str,
            "title": title,
            "description": description,
            "doc_type": doc_type,
            "agent_preset": agent_preset,
            "custom_agent_id": str(custom_agent_id) if custom_agent_id else None,
            "team_id": str(team_id) if team_id else None,
            "persona_prompt": persona_prompt,
            "outline": "",
            "main_tex_path": "main.tex",
            "pdf_path": None,
            "steps": [],
            "status": "planning",
            "error": None,
        }

        task = asyncio.create_task(self._run_workflow(doc_str, initial_state))
        self._tasks[doc_str] = task
        task.add_done_callback(lambda _: self._tasks.pop(doc_str, None))

    async def _run_workflow(self, document_id: str, state: DocumentState | None):
        try:
            graph = await self._get_graph()
            config = {"configurable": {"thread_id": document_id}}

            async with get_session() as session:
                await db_utils.update_document_status(session, UUID(document_id), "running")

            final_state = await graph.ainvoke(state, config=config)
            
            # Check final state for errors
            if isinstance(final_state, dict):
                final_status = final_state.get("status", "done")
                final_error = final_state.get("error")
                
                async with get_session() as session:
                    if final_status == "failed":
                        await db_utils.update_document_status(session, UUID(document_id), "failed")
                    else:
                        await db_utils.update_document_status(session, UUID(document_id), "done")
            else:
                async with get_session() as session:
                    await db_utils.update_document_status(session, UUID(document_id), "done")

        except asyncio.CancelledError:
            LOGGER.info("Document workflow cancelled: %s", document_id)
            async with get_session() as session:
                await db_utils.update_document_status(session, UUID(document_id), "stopped")
            raise
        except Exception as e:
            LOGGER.exception("Document workflow failed for %s: %s", document_id, e)
            # Emit error event to UI
            from backend.core.document_event_bus import emit_document_event
            await emit_document_event(
                document_id,
                f"Workflow failed: {str(e)[:500]}",
                agent="orchestrator",
                level="error"
            )
            async with get_session() as session:
                await db_utils.update_document_status(session, UUID(document_id), "failed")

    async def resume_document(self, document_id: UUID) -> None:
        doc_str = str(document_id)
        LOGGER.info("Resuming document %s", doc_str)
        try:
            graph = await self._get_graph()
            config = {"configurable": {"thread_id": doc_str}}
            snapshot = await graph.aget_state(config)
            if not snapshot.values:
                LOGGER.warning("No checkpoint found for document %s. Marking failed.", doc_str)
                async with get_session() as session:
                    await db_utils.update_document_status(session, document_id, "failed")
                return

            task = asyncio.create_task(self._run_workflow(doc_str, state=None))
            self._tasks[doc_str] = task
            task.add_done_callback(lambda _: self._tasks.pop(doc_str, None))
        except Exception as e:
            LOGGER.error("Failed to resume document %s: %s", doc_str, e)
            async with get_session() as session:
                await db_utils.update_document_status(session, document_id, "failed")

    async def request_stop(self, document_id: str) -> None:
        task = self._tasks.get(document_id)
        if task and not task.done():
            task.cancel()

    async def shutdown(self) -> None:
        await close_checkpointer()


document_orchestrator = DocumentOrchestrator()

