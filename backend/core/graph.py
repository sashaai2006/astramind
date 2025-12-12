from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.base import BaseCheckpointSaver

from backend.agents.ceo import CEOAgent
from backend.agents.developer import DeveloperAgent
from backend.agents.researcher import ResearcherAgent
from backend.agents.tester import TesterAgent
from backend.core.state import ProjectState
from backend.core.event_bus import emit_event
from backend.utils.formatter import CodeFormatter
from backend.memory.db import get_session
from backend.memory import utils as db_utils
from backend.settings import get_settings
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)

def _build_research_query(description: str, target: str, tech_stack: str | None = None) -> str:
    desc = (description or "").strip()
    tgt = (target or "").strip()
    stack = (tech_stack or "").strip()
    parts = [desc]
    if stack:
        parts.append(f"tech stack {stack}")
    if tgt:
        parts.append(f"target {tgt}")
    parts.append("best practices 2025")
    return " ".join(p for p in parts if p)


async def research_node(state: ProjectState) -> Dict[str, Any]:
    """Performs web search based on the project description/plan and stores results in state."""
    project_id = state["project_id"]
    settings = get_settings()
    if not getattr(settings, "enable_web_search", True):
        return {}

    description = state.get("description", "")
    target = state.get("target", "")
    tech_stack = state.get("tech_stack")
    query = _build_research_query(description, target, tech_stack)

    await emit_event(project_id, f"Research: {query}", agent="researcher")

    researcher = ResearcherAgent()
    # Add timeout to prevent blocking workflow (15s max)
    try:
        payload = await asyncio.wait_for(
            researcher.search(query, project_id=project_id, max_results=getattr(settings, "max_search_results", 5)),
            timeout=15.0
        )
    except asyncio.TimeoutError:
        LOGGER.warning("Research timed out after 15s, continuing without results")
        await emit_event(project_id, "Research timed out, continuing...", agent="researcher", level="warning")
        payload = {"query": query, "provider": None, "results": [], "cached": False, "error": "timeout"}
    except Exception as e:
        LOGGER.warning("Research failed: %s", e)
        await emit_event(project_id, f"Research failed: {str(e)[:100]}", agent="researcher", level="warning")
        payload = {"query": query, "provider": None, "results": [], "cached": False, "error": str(e)[:200]}

    # Stream top snippets to UI (short)
    results = payload.get("results", []) or []
    if payload.get("cached"):
        await emit_event(project_id, "Research cache hit", agent="researcher")
    for r in results[: min(5, len(results))]:
        title = str(r.get("title", "")).strip()
        url = str(r.get("url", "")).strip()
        if title and url:
            await emit_event(project_id, f"- {title} ({url})", agent="researcher")
        elif title:
            await emit_event(project_id, f"- {title}", agent="researcher")

    prev_queries = list(state.get("research_queries") or [])
    if query not in prev_queries:
        prev_queries.append(query)

    return {"research_results": payload, "research_queries": prev_queries}


async def plan_node(state: ProjectState) -> Dict[str, Any]:
    """Generates the project plan."""
    project_id = state["project_id"]
    description = state["description"]
    target = state["target"]
    persona_prompt = state.get("persona_prompt", "") or ""
    agent_preset = state.get("agent_preset", "") or ""
    settings = get_settings()

    # #region agent log
    with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
        import json as json_lib, time
        f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"graph.py:23","message":"plan_node entry","data":{"project_id":project_id,"description_len":len(description)},"timestamp":int(time.time()*1000)}) + '\n')
    # #endregion

    await emit_event(project_id, "Planning project architecture...", agent="ceo")
    
    # Log agent selection for debugging
    if agent_preset:
        LOGGER.info("CEO planning with agent_preset=%s", agent_preset)
        await emit_event(project_id, f"Using agent: {agent_preset}", agent="ceo", level="info")

    ceo = CEOAgent()
    research_payload = state.get("research_results")
    research_queries = list(state.get("research_queries") or [])

    # Optional pre-planning research (non-blocking, with short timeout)
    # Don't block planning if research is slow - it will happen in research_node anyway
    if getattr(settings, "enable_web_search", True) and not research_payload:
        try:
            q = _build_research_query(description, target, state.get("tech_stack"))
            researcher = ResearcherAgent()
            # Fast timeout (5s) - if it takes longer, skip pre-plan research
            # Research will happen in research_node anyway
            research_payload = await asyncio.wait_for(
                researcher.search(q, project_id=project_id, max_results=getattr(settings, "max_search_results", 5)),
                timeout=5.0
            )
            if q not in research_queries:
                research_queries.append(q)
        except asyncio.TimeoutError:
            LOGGER.debug("Pre-plan research timed out (skipping, will use research_node)")
            research_payload = None
        except Exception as e:
            LOGGER.debug("Pre-plan research failed: %s (skipping)", e)
            research_payload = None
    
    # Add timeout to prevent hanging on rate limits
    try:
        # #region agent log
        with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
            import json as json_lib, time
            f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"graph.py:35","message":"plan_node before ceo.plan","data":{},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
        plan = await asyncio.wait_for(
            ceo.plan(
                description,
                target,
                persona_prompt=persona_prompt,
                agent_preset=agent_preset,
                research_results=research_payload,
            ),
            timeout=180.0,
        )
        # #region agent log
        with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
            import json as json_lib, time
            f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"graph.py:38","message":"plan_node after ceo.plan","data":{"plan_len":len(plan) if plan else 0},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
    except asyncio.TimeoutError:
        # #region agent log
        with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
            import json as json_lib, time
            f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"graph.py:40","message":"plan_node timeout","data":{},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
        error_msg = "CEO plan generation timed out (exceeded 180s). This may be due to rate limits."
        LOGGER.error(error_msg)
        await emit_event(project_id, error_msg, agent="ceo", level="error")
        raise RuntimeError(error_msg)
    except Exception as e:
        # #region agent log
        with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
            import json as json_lib, time
            f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"graph.py:47","message":"plan_node exception","data":{"exc_type":type(e).__name__,"exc_msg":str(e)[:300]},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
        raise
    
    if not plan:
        # #region agent log
        with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
            import json as json_lib, time
            f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"graph.py:50","message":"plan_node empty plan","data":{},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
        error_msg = "CEO failed to generate plan (returned empty)"
        LOGGER.error(error_msg)
        await emit_event(project_id, error_msg, agent="ceo", level="error")
        raise ValueError(error_msg)

    # Extract tech_stack from first step
    tech_stack = "unknown"
    if plan and len(plan) > 0:
        first_step = plan[0]
        payload = first_step.get("payload", {})
        tech_stack = payload.get("tech_stack", "unknown")

    # #region agent log
    with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
        import json as json_lib, time
        f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"graph.py:62","message":"plan_node before emit Plan generated","data":{"plan_len":len(plan),"tech_stack":tech_stack},"timestamp":int(time.time()*1000)}) + '\n')
    # #endregion
    await emit_event(project_id, f"Plan generated with {len(plan)} steps", agent="ceo")
    LOGGER.info("Plan node completed: %d steps, tech_stack=%s", len(plan), tech_stack)
    
    # #region agent log
    with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
        import json as json_lib, time
        f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"graph.py:66","message":"plan_node returning","data":{"plan_len":len(plan),"status":"generating"},"timestamp":int(time.time()*1000)}) + '\n')
    # #endregion
    return {
        "plan": plan, 
        "tech_stack": tech_stack,
        "research_results": research_payload,
        "research_queries": research_queries,
        "status": "generating"
    }


async def generate_node(state: ProjectState) -> Dict[str, Any]:
    """Executes the plan steps."""
    project_id = state["project_id"]
    plan = state["plan"]
    current_idx = state.get("current_step_idx", 0)
    
    # #region agent log
    with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
        import json as json_lib, time
        f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"graph.py:65","message":"generate_node entry","data":{"project_id":project_id,"plan_len":len(plan),"current_idx":current_idx},"timestamp":int(time.time()*1000)}) + '\n')
    # #endregion
    LOGGER.info("Generate node starting: project_id=%s, plan_steps=%d, current_idx=%d", project_id, len(plan), current_idx)
    await emit_event(project_id, f"Starting code generation ({len(plan)} steps)...", agent="system")
    
    # We execute ALL remaining steps here for now, 
    # but strictly we could do one by one. 
    # To keep it compatible with existing bulk logic, we iterate.
    # Ideally, we should yield control back to graph after each step 
    # if we want granular checkpointing per step.
    
    settings = get_settings()
    semaphore = asyncio.Semaphore(settings.llm_semaphore)
    developer = DeveloperAgent(semaphore)
    from backend.core.orchestrator import orchestrator
    stop_event = orchestrator.get_stop_event(project_id)

    # Helper for broadcast
    async def on_message(target: str, msg: str) -> None:
        await emit_event(project_id, msg, agent="developer", data={"target": target})

    context = {
        "project_id": project_id,
        "title": state["title"],
        "description": state["description"],
        "target": state["target"],
        "tech_stack": state.get("tech_stack"),
        "agent_preset": state.get("agent_preset"),
        "custom_agent_id": state.get("custom_agent_id"),
        "team_id": state.get("team_id"),
        "persona_prompt": state.get("persona_prompt"),
        "research_results": state.get("research_results"),
        "research_queries": state.get("research_queries"),
    }

    # Identify groups
    from backend.core.step_utils import group_steps
    groups = group_steps(plan[current_idx:])
    
    total_groups = len(groups)
    LOGGER.info("Generate node: %d groups to execute", total_groups)
    
    for group_idx, (group_id, steps) in enumerate(groups, 1):
        group_msg = f"Executing group {group_id} ({group_idx}/{total_groups})"
        LOGGER.info(group_msg)
        await emit_event(project_id, group_msg, agent="system")
        
        # Run steps in parallel
        try:
            await asyncio.gather(
                *[
                    _run_single_step(developer, step, context, stop_event, on_message)
                    for step in steps
                ],
                return_exceptions=False
            )
            await emit_event(project_id, f"Group {group_id} completed", agent="system")
        except Exception as e:
            LOGGER.error("Group %s failed: %s", group_id, e, exc_info=True)
            await emit_event(project_id, f"Group {group_id} failed: {str(e)[:200]}", agent="system", level="error")
            raise
        
        # Update progress
        current_idx += len(steps)

    return {
        "current_step_idx": len(plan), # All done
        "status": "testing"
    }


async def _run_single_step(developer, step, context, stop_event, on_message):
    project_id = context["project_id"]
    step_name = step.get("name", "unknown")
    
    if stop_event.is_set():
        raise asyncio.CancelledError()

    await emit_event(project_id, f"Step {step_name} started", agent="developer")
    
    try:
        await developer.run(step, context, stop_event, on_message)
        await emit_event(project_id, f"Step {step_name} finished", agent="developer")
    except Exception as e:
        await emit_event(project_id, f"Step {step_name} failed: {e}", agent="developer", level="error")
        raise e


async def test_node(state: ProjectState) -> Dict[str, Any]:
    """Runs tests on the generated project."""
    project_id = state["project_id"]
    await emit_event(project_id, "Formatting code...", agent="system")
    
    settings = get_settings()
    project_path = settings.projects_root / project_id
    await CodeFormatter.format_project(project_path)
    
    await emit_event(project_id, "Running tests...", agent="tester")
    
    tester = TesterAgent()
    context = {
        "project_id": project_id,
        "title": state["title"],
        "description": state["description"],
        "target": state["target"],
        "tech_stack": state.get("tech_stack"),
        "agent_preset": state.get("agent_preset"),
        "custom_agent_id": state.get("custom_agent_id"),
        "team_id": state.get("team_id"),
        "persona_prompt": state.get("persona_prompt"),
        "research_results": state.get("research_results"),
        "research_queries": state.get("research_queries"),
    }
    
    results = await tester.test_project(state["project_id"], context)
    
    return {
        "test_results": results,
        "status": "correcting" if not results["passed"] else "done"
    }


async def correct_node(state: ProjectState) -> Dict[str, Any]:
    """Auto-corrects issues if tests failed."""
    project_id = state["project_id"]
    issues = state["test_results"]["issues"]
    retry_count = state.get("retry_count", 0) + 1
    
    await emit_event(
        project_id, 
        f"Tests failed ({len(issues)} issues). Attempting correction {retry_count}...", 
        agent="developer",
        level="warning",
    )
    
    settings = get_settings()
    semaphore = asyncio.Semaphore(settings.llm_semaphore)
    developer = DeveloperAgent(semaphore)
    from backend.core.orchestrator import orchestrator
    stop_event = orchestrator.get_stop_event(project_id)
    
    context = {
        "project_id": project_id,
        "title": state["title"],
        "description": state["description"],
        "target": state["target"],
        "tech_stack": state.get("tech_stack"),
        "agent_preset": state.get("agent_preset"),
        "custom_agent_id": state.get("custom_agent_id"),
        "team_id": state.get("team_id"),
        "persona_prompt": state.get("persona_prompt"),
        "research_results": state.get("research_results"),
        "research_queries": state.get("research_queries"),
    }
    
    await developer.auto_correct(context, issues, stop_event)
    
    # Re-format
    project_path = settings.projects_root / project_id
    await CodeFormatter.format_project(project_path)
    
    return {
        "retry_count": retry_count,
        "status": "testing" # Go back to testing
    }


async def finalize_node(state: ProjectState) -> Dict[str, Any]:
    """Marks project as completed."""
    project_id = state["project_id"]
    from uuid import UUID
    
    if state["test_results"] and not state["test_results"]["passed"]:
         await emit_event(project_id, "Max retries reached. Project finished with warnings.", agent="system", level="warning")
    else:
         await emit_event(project_id, "Project completed successfully!", agent="system")
         
    async with get_session() as session:
        await db_utils.update_project_status(session, UUID(state["project_id"]), "done")
        
    return {"status": "done"}


# --- Graph Construction ---

def create_project_graph(checkpointer: BaseCheckpointSaver):
    workflow = StateGraph(ProjectState)

    workflow.add_node("plan_node", plan_node)
    workflow.add_node("research_node", research_node)
    workflow.add_node("generate_node", generate_node)
    workflow.add_node("test_node", test_node)
    workflow.add_node("correct_node", correct_node)
    workflow.add_node("finalize_node", finalize_node)

    workflow.set_entry_point("plan_node")

    # Optional web research stage between plan and generate
    def should_research(state: ProjectState) -> Literal["research_node", "generate_node"]:
        settings = get_settings()
        if getattr(settings, "enable_web_search", True):
            return "research_node"
        return "generate_node"

    workflow.add_conditional_edges("plan_node", should_research)
    workflow.add_edge("research_node", "generate_node")
    workflow.add_edge("generate_node", "test_node")

    def should_correct(state: ProjectState) -> Literal["correct_node", "finalize_node"]:
        results = state.get("test_results", {})
        passed = results.get("passed", False)
        retries = state.get("retry_count", 0)
        max_retries = 2 # Configurable
        
        if not passed and retries < max_retries:
            return "correct_node"
        return "finalize_node"

    workflow.add_conditional_edges(
        "test_node",
        should_correct
    )

    workflow.add_edge("correct_node", "test_node")
    workflow.add_edge("finalize_node", END)

    return workflow.compile(checkpointer=checkpointer)
