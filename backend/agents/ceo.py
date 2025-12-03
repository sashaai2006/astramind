from __future__ import annotations

import json
from typing import Any, Dict, List
from uuid import uuid4

from backend.llm.adapter import get_llm_adapter
from backend.settings import get_settings
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)


class CEOAgent:
    """Generates a lightweight DAG describing required build steps."""

    async def plan(self, description: str, target: str) -> List[Dict[str, Any]]:
        settings = get_settings()
        if settings.llm_mode == "mock":
            return self._mock_plan(description, target)
        return await self._llm_plan(description, target)

    async def _llm_plan(self, description: str, target: str) -> List[Dict[str, Any]]:
        prompt = (
            "You are a technical CEO. Create a SIMPLE, FAST execution plan for an MVP.\n"
            f"Project: {description}\n"
            f"Target: {target}\n"
            "\n"
            "CRITICAL: Keep it SIMPLE and FAST. Prefer 1-2 steps maximum.\n"
            "Combine related tasks into one step (e.g., 'build_project' instead of separate frontend/backend steps).\n"
            "\n"
            "Output JSON:\n"
            "{\n"
            '  "_thought": "Brief reasoning (1 sentence)",\n'
            '  "steps": [\n'
            '    {\n'
            '      "name": "build_project",\n'
            '      "agent": "developer",\n'
            '      "parallel_group": "main",\n'
            '      "payload": {\n'
            '        "files": [\n'
            '          {"path": "index.html", "content": "Detailed instructions for main HTML file"},\n'
            '          {"path": "script.js", "content": "Instructions for main JS logic"},\n'
            '          {"path": "README.md", "content": "Project description and how to run"}\n'
            '        ]\n'
            '      }\n'
            '    }\n'
            '  ]\n'
            "}\n"
            "\n"
            "RULES:\n"
            "1. MINIMIZE STEPS: 1-2 steps maximum. Combine everything possible.\n"
            "2. ONE parallel_group for all steps (e.g., 'main')\n"
            "3. DETAILED file instructions (natural language, not code)\n"
            "4. Return ONLY valid JSON, no markdown\n"
        )
        adapter = get_llm_adapter()
        try:
            LOGGER.info("CEO requesting plan from LLM...")
            response = await adapter.acomplete(prompt, json_mode=True)
            LOGGER.info("CEO received plan (len=%d)", len(response))
            
            # Parse response
            data = json.loads(response)
            
            # Handle Thought Streaming if present
            if "_thought" in data:
                # Ideally we would broadcast this, but CEO doesn't have WS manager context yet.
                # We'll log it for now.
                LOGGER.info("CEO Thought: %s", data["_thought"])
                
            steps = data.get("steps", [])
            if isinstance(data, list): # Fallback if LLM returned list directly
                steps = data

            # Ensure IDs
            for step in steps:
                if "id" not in step:
                    step["id"] = str(uuid4())
            return steps
        except Exception as exc:
            LOGGER.error("CEO plan generation failed: %s", exc)
            # Fallback to simplified plan
            return [{
                "id": str(uuid4()),
                "name": "build_project",
                "agent": "developer",
                "parallel_group": "main",
                "payload": {
                    "files": [
                        {"path": "index.html", "content": f"Create {target} project: {description}"},
                        {"path": "README.md", "content": f"# {description}"},
                    ]
                },
            }]

    def _mock_plan(self, description: str, target: str) -> List[Dict[str, Any]]:
        """Single-step plan for maximum speed."""
        return [
            {
                "id": str(uuid4()),
                "name": "build_project",
                "agent": "developer",
                "parallel_group": "main",
                "payload": {
                    "files": [
                        {"path": "index.html", "content": f"Create complete {target} project: {description}"},
                        {"path": "README.md", "content": f"# {description}\n\nTarget: {target}"},
                        {"path": "meta.json", "content": json.dumps({"description": description, "target": target}, indent=2)},
                    ]
                },
            },
        ]
