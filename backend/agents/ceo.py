from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional
from uuid import uuid4

from backend.llm.adapter import get_llm_adapter
from backend.settings import get_settings
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)


class CEOAgent:
    """Generates a lightweight DAG describing required build steps."""

    def __init__(self, semaphore: Optional[asyncio.Semaphore] = None) -> None:
        self._adapter = None
        self._settings = get_settings()
        self._semaphore = semaphore or asyncio.Semaphore(1)

    @property
    def adapter(self):
        if self._adapter is None:
            self._adapter = get_llm_adapter()
        return self._adapter

    async def plan(
        self,
        description: str,
        target: str,
        persona_prompt: str = "",
        agent_preset: str = "",
        research_results: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        settings = get_settings()
        if settings.llm_mode == "mock":
            return self._mock_plan(description, target, persona_prompt=persona_prompt, agent_preset=agent_preset, research_results=research_results)
        return await self._llm_plan(description, target, persona_prompt=persona_prompt, agent_preset=agent_preset, research_results=research_results)

    def _extract_tech_hints_from_team(self, persona_prompt: str) -> Dict[str, Any]:
        """Parse team composition and return tech preferences."""
        hints = {"languages": [], "formats": [], "has_cpp": False, "has_python": False, "has_latex": False, "has_technical_writer": False}
        if not persona_prompt:
            return hints
        
        prompt_lower = persona_prompt.lower()
        
        # Detect C++ Developer
        if "c++" in prompt_lower or "cpp" in prompt_lower or "senior_cpp" in prompt_lower:
            hints["languages"].append("cpp")
            hints["has_cpp"] = True
        
        # Detect Python Developer
        if "python" in prompt_lower or "senior_python" in prompt_lower:
            hints["languages"].append("python")
            hints["has_python"] = True
        
        # Detect TypeScript/JavaScript
        if "typescript" in prompt_lower or "fullstack_ts" in prompt_lower or "javascript" in prompt_lower:
            hints["languages"].append("typescript")
        
        # Detect LaTeX Writer
        if "latex" in prompt_lower or "latex_writer" in prompt_lower:
            hints["formats"].append("latex")
            hints["has_latex"] = True
        
        # Detect Technical Writer
        if "technical writer" in prompt_lower or "technical_writer" in prompt_lower:
            hints["formats"].append("markdown")
            hints["has_technical_writer"] = True
        
        return hints

    async def _llm_plan(
        self,
        description: str,
        target: str,
        persona_prompt: str = "",
        agent_preset: str = "",
        research_results: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        settings = get_settings()
        LOGGER.info("CEO starting LLM plan generation (description length=%d, target=%s, agent_preset=%s)", len(description), target, agent_preset)
        
        # Extract tech hints from team composition AND agent preset
        tech_hints = self._extract_tech_hints_from_team(persona_prompt)
        
        # Override with agent_preset if explicitly set
        if agent_preset:
            preset_lower = agent_preset.lower()
            if "python" in preset_lower or "senior_python" in preset_lower:
                tech_hints["languages"] = ["python"]
                tech_hints["has_python"] = True
                tech_hints["has_cpp"] = False
            elif "cpp" in preset_lower or "c++" in preset_lower or "senior_cpp" in preset_lower:
                tech_hints["languages"] = ["cpp"]
                tech_hints["has_cpp"] = True
                tech_hints["has_python"] = False
            elif "typescript" in preset_lower or "fullstack_ts" in preset_lower:
                tech_hints["languages"] = ["typescript"]
                tech_hints["has_python"] = False
                tech_hints["has_cpp"] = False

        # Web research section (if available)
        research_section = ""
        if research_results and isinstance(research_results, dict):
            try:
                q = str(research_results.get("query", "")).strip()
                provider = str(research_results.get("provider", "")).strip()
                results = research_results.get("results", []) or []
                lines: List[str] = []
                for r in results[:5]:
                    title = str(r.get("title", "")).strip()
                    url = str(r.get("url", "")).strip()
                    snippet = str(r.get("snippet", "")).strip()
                    if title and url:
                        lines.append(f"- {title} ({url})")
                    elif title:
                        lines.append(f"- {title}")
                    if snippet:
                        lines.append(f"  {snippet[:200]}")
                body = "\n".join(lines)
                research_section = (
                    "\n=== WEB RESEARCH (UPDATED BEST PRACTICES) ===\n"
                    + (f"Query: {q}\n" if q else "")
                    + (f"Provider: {provider}\n" if provider else "")
                    + (body + "\n" if body else "")
                )
            except Exception:
                research_section = ""
        
        # Build team section
        team_section = ""
        task_distribution_rules = ""
        rules = []
        
        # CRITICAL: If agent_preset is set, it takes ABSOLUTE PRIORITY
        if agent_preset:
            preset_lower = agent_preset.lower()
            if "python" in preset_lower or "senior_python" in preset_lower:
                rules.append("🚨🚨🚨 CRITICAL: User selected PYTHON DEVELOPER preset → ALL code MUST be Python (.py, requirements.txt)")
                rules.append("   - Use Python 3.10+, type hints, async/await where appropriate")
                rules.append("   - ABSOLUTELY FORBIDDEN: JavaScript, TypeScript, HTML, CSS, or any web files")
                rules.append("   - FORBIDDEN FILES: index.html, script.js, style.css, package.json, tsconfig.json")
                rules.append("   - ALLOWED FILES: ONLY .py files (main.py, game.py, etc.), requirements.txt, README.md")
                rules.append("   - tech_stack MUST be 'python' in ALL steps")
            elif "cpp" in preset_lower or "c++" in preset_lower or "senior_cpp" in preset_lower:
                rules.append("🚨🚨🚨 CRITICAL: User selected C++ DEVELOPER preset → ALL code MUST be C++ (.cpp, .h, CMakeLists.txt)")
                rules.append("   - Use modern C++17/20 features, smart pointers, STL")
                rules.append("   - ABSOLUTELY FORBIDDEN: JavaScript, TypeScript, Python, HTML, CSS")
                rules.append("   - ALLOWED FILES: ONLY .cpp, .h, CMakeLists.txt, Makefile, README.md")
                rules.append("   - tech_stack MUST be 'cpp' in ALL steps")
            elif "typescript" in preset_lower or "fullstack_ts" in preset_lower:
                rules.append("🚨🚨🚨 CRITICAL: User selected TYPESCRIPT DEVELOPER preset → ALL code MUST be TypeScript (.ts, .tsx)")
                rules.append("   - Use React, Next.js, Node.js with TypeScript")
                rules.append("   - ABSOLUTELY FORBIDDEN: Python, C++, or other languages")
                rules.append("   - tech_stack MUST be 'typescript' in ALL steps")
        
        if persona_prompt and persona_prompt.strip():
            team_section = (
                f"\n=== YOUR TEAM ===\n"
                f"{persona_prompt}\n"
            )
            
            # Build task distribution rules based on team composition
            if not agent_preset:
                if tech_hints["has_cpp"]:
                    rules.append("1. Team has C++ Developer → ALL code steps MUST use C++ (.cpp, .h, CMakeLists.txt, Makefile)")
                    rules.append("   - Use modern C++17/20 features, smart pointers, STL")
                    rules.append("   - NO JavaScript, TypeScript, Python, or other languages")
                elif tech_hints["has_python"]:
                    rules.append("1. Team has Python Developer → ALL code steps MUST use Python (.py, requirements.txt)")
                    rules.append("   - Use Python 3.10+, type hints, async/await where appropriate")
                    rules.append("   - NO JavaScript, TypeScript, C++, or other languages")
                elif tech_hints["languages"]:
                    primary_lang = tech_hints["languages"][0]
                    rules.append(f"1. Team has {primary_lang} Developer → ALL code steps MUST use {primary_lang}")
            
            if tech_hints["has_latex"]:
                rules.append("2. Team has LaTeX Writer → documentation steps MUST produce .tex files (NOT .md)")
                rules.append("   - Use LaTeX format: \\documentclass, \\section, proper math mode")
                rules.append("   - Create separate step with agent='writer' for documentation")
            elif tech_hints["has_technical_writer"]:
                rules.append("2. Team has Technical Writer → documentation steps MUST produce .md files")
                rules.append("   - Use Markdown format: headings, lists, code blocks")
                rules.append("   - Create separate step with agent='writer' for documentation")
        
        if rules:
            rules.append("3. DISTRIBUTE tasks between team members:")
            rules.append("   - Code implementation → agent='developer' (use team's language)")
            rules.append("   - Documentation → agent='writer' (use team's format: .tex or .md)")
            rules.append("   - Architecture/Planning → agent='ceo'")
            rules.append("4. Each step's tech_stack MUST match the team's specialization")
            rules.append("5. If team has multiple specialists, create SEPARATE steps for each role")
            
            task_distribution_rules = "\n=== TASK DISTRIBUTION RULES ===\n" + "\n".join(rules) + "\n"
        
        prompt = (
            "You are a LEGENDARY SOFTWARE ARCHITECT with 25+ years of experience.\n"
            "You have deep expertise in Computer Science fundamentals:\n"
            "- Algorithms, Data Structures, System Design\n"
            "- Software Engineering principles (SOLID, DRY, KISS)\n"
            "- Clean Architecture, Design Patterns\n"
            "- You choose the RIGHT tool for the job, never forcing a specific technology\n"
            + team_section
            + research_section +
            f"=== PROJECT REQUEST ===\n"
            f"Description: {description}\n"
            f"Target: {target}\n"
            + task_distribution_rules +
            "\n=== YOUR TASK ===\n"
            "1. READ the description carefully\n"
            "2. CHECK if user selected an AGENT PRESET\n"
            "3. Create 4-6 focused implementation steps, DISTRIBUTING work between team members\n"
            "\n"
            "=== OUTPUT FORMAT (JSON) ===\n"
            "{\n"
            '  "_thought": "User explicitly asked for [X]. I will use [X] because user requested it.",\n'
            '  "tech_stack": "what_user_requested",\n'
            '  "steps": [\n'
            '    {\n'
            '      "name": "step_name",\n'
            '      "agent": "developer",\n'
            '      "parallel_group": "setup|core|features|null",\n'
            '      "payload": {\n'
            '        "tech_stack": "SAME_AS_ROOT",\n'
            '        "files": [\n'
            '          {"path": "filename.ext", "content": "What to implement"}\n'
            '        ]\n'
            '      }\n'
            '    }\n'
            '  ]\n'
            "}\n"
            "\n"
            "=== RULES ===\n"
            "1. tech_stack in root AND every payload\n"
            "2. Step 1: config files + entry point appropriate for the chosen stack\n"
            "3. content field: describe WHAT to implement\n"
            "4. NO MIXING technologies\n"
            "5. Return ONLY JSON, no text before or after\n"
        )

        # Rate limit handling
        rate_limit_backoffs = [10, 20, 40]
        rate_limit_attempt = 0
        
        def _is_rate_limit_error(exc: Exception) -> bool:
            try:
                from tenacity import RetryError
                if isinstance(exc, RetryError):
                    last = exc.last_attempt.exception()
                    if last and last.__class__.__name__ == "RateLimitError":
                        return True
            except Exception:
                pass
            name = exc.__class__.__name__
            if name == "RateLimitError":
                return True
            txt = (str(exc) or "").lower()
            return ("rate limit" in txt) or ("ratelimit" in txt) or ("RateLimitError" in repr(exc))
        
        try:
            LOGGER.info("CEO calling LLM adapter (mode=%s)...", settings.llm_mode)
            
            while True:
                try:
                    async with self._semaphore:
                        response = await self.adapter.acomplete(prompt, json_mode=True)
                    break  # Success
                except Exception as exc:
                    if _is_rate_limit_error(exc) and rate_limit_attempt < len(rate_limit_backoffs):
                        wait_s = rate_limit_backoffs[rate_limit_attempt]
                        rate_limit_attempt += 1
                        LOGGER.warning("CEO rate limit hit, waiting %ds...", wait_s)
                        await asyncio.sleep(wait_s)
                        continue
                    raise
            
            LOGGER.info("CEO received plan response (length=%d chars)", len(response or ""))
            
            if not response or not response.strip():
                raise ValueError("CEO received empty response from LLM")
            
            data = json.loads(response)
            
            if "_thought" in data:
                LOGGER.info("CEO Thought: %s", data["_thought"])
                
            steps = data.get("steps", [])
            if isinstance(data, list):
                steps = data

            for step in steps:
                if "id" not in step:
                    step["id"] = str(uuid4())
            
            if len(steps) > 10:
                steps = steps[:8]
            elif len(steps) < 3:
                return self._mock_plan(description, target, persona_prompt=persona_prompt, agent_preset=agent_preset, research_results=research_results)
            
            return steps
        except Exception as exc:
            LOGGER.error("CEO plan generation failed: %s", exc, exc_info=True)
            return self._mock_plan(description, target, persona_prompt=persona_prompt, agent_preset=agent_preset, research_results=research_results)

    def _detect_stack_from_description(self, description: str, persona_prompt: str = "", agent_preset: str = "") -> str:
        """Detect tech stack from user's description, team composition, and agent preset."""
        if agent_preset:
            preset_lower = agent_preset.lower()
            if "python" in preset_lower or "senior_python" in preset_lower:
                return 'python'
            if "cpp" in preset_lower or "c++" in preset_lower or "senior_cpp" in preset_lower:
                return 'cpp'
            if "typescript" in preset_lower or "fullstack_ts" in preset_lower:
                return 'typescript'
        
        if persona_prompt:
            tech_hints = self._extract_tech_hints_from_team(persona_prompt)
            if tech_hints["has_cpp"]:
                return 'cpp'
            if tech_hints["has_python"]:
                return 'python'
            if "typescript" in tech_hints["languages"]:
                return 'typescript'
        
        desc_lower = description.lower()
        if any(word in desc_lower for word in ['c++', 'cpp', 'с++', 'плюс']):
            return 'cpp'
        if any(word in desc_lower for word in ['rust', 'cargo']):
            return 'rust'
        if any(word in desc_lower for word in ['go ', 'golang']):
            return 'go'
        if any(word in desc_lower for word in ['python', 'питон', 'py ']):
            return 'python'
        
        return 'python' if 'api' in desc_lower else 'vanilla'

    def _mock_plan(
        self,
        description: str,
        target: str,
        persona_prompt: str = "",
        agent_preset: str = "",
        research_results: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        """Create a plan based on detected tech stack."""
        tech_stack = self._detect_stack_from_description(description, persona_prompt=persona_prompt, agent_preset=agent_preset)
        
        if tech_stack == 'cpp':
            files_setup = [
                {"path": "Makefile", "content": f"Build rules for: {description}"},
                {"path": "main.cpp", "content": f"Entry point for: {description}"},
            ]
            files_core = [
                {"path": "solution.hpp", "content": "Header declarations"},
                {"path": "solution.cpp", "content": "Implementation"},
            ]
        elif tech_stack == 'python':
            files_setup = [
                {"path": "requirements.txt", "content": "Dependencies"},
                {"path": "main.py", "content": f"Entry point for: {description}"},
            ]
            files_core = [
                {"path": "core.py", "content": "Core logic"},
            ]
        else:
            files_setup = [
                {"path": "index.html", "content": "HTML structure"},
                {"path": "script.js", "content": "JS logic"},
            ]
            files_core = []
        
        steps = [
            {
                "id": str(uuid4()),
                "name": "setup",
                "agent": "developer",
                "parallel_group": "setup",
                "payload": {
                    "tech_stack": tech_stack,
                    "files": files_setup,
                },
            },
        ]
        
        if files_core:
            steps.append({
                "id": str(uuid4()),
                "name": "core",
                "agent": "developer",
                "parallel_group": "core",
                "payload": {
                    "tech_stack": tech_stack,
                    "files": files_core,
                },
            })
        
        return steps
