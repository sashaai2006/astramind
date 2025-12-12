from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List
from uuid import uuid4

from backend.llm.adapter import get_llm_adapter
from backend.settings import get_settings
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)


class CEOAgent:
    """Generates a lightweight DAG describing required build steps."""

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
        LOGGER.info("CEO starting LLM plan generation (description length=%d, target=%s, agent_preset=%s)", len(description), target, agent_preset)
        
        # Extract tech hints from team composition AND agent preset
        # If agent_preset is set, use it to determine technology (highest priority)
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
            
            # Build task distribution rules based on team composition (if no agent_preset override)
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
            "2. CHECK if user selected an AGENT PRESET (highest priority - MUST respect it)\n"
            "3. If user selected Python Developer → ALL files MUST be .py (NO HTML, NO JS, NO CSS)\n"
            "4. If user selected C++ Developer → ALL files MUST be .cpp/.h (NO other languages)\n"
            "5. If user selected TypeScript Developer → ALL files MUST be .ts/.tsx (NO Python, NO C++)\n"
            "6. If team has specialists → USE THEIR TECHNOLOGY (override user preference if team is specialized)\n"
            "7. If user said a specific language AND team supports it → USE THAT LANGUAGE\n"
            "8. If unclear → choose based on the problem domain (NOT your preference)\n"
            "9. Create 4-6 focused implementation steps, DISTRIBUTING work between team members\n"
            "\n"
            "=== CRITICAL: RESPECT USER'S AGENT SELECTION ===\n"
            + (f"🚨 USER SELECTED AGENT PRESET: {agent_preset.upper()}\n" if agent_preset else "")
            + "If user selected Python Developer → ALL code MUST be Python (.py files ONLY, NO exceptions)\n"
            + "If user selected C++ Developer → ALL code MUST be C++ (.cpp files ONLY, NO exceptions)\n"
            + "If user selected TypeScript Developer → ALL code MUST be TypeScript (.ts files ONLY, NO exceptions)\n"
            + "If your team has C++ Developer → ALL code MUST be C++ (NO exceptions)\n"
            + "If your team has Python Developer → ALL code MUST be Python (NO exceptions)\n"
            + "If your team has LaTeX Writer → documentation MUST be .tex (NOT .md)\n"
            + "If your team has Technical Writer → documentation MUST be .md\n"
            + "Do NOT mix technologies. Each team member works in their specialty.\n"
            + "🚨 ABSOLUTE RULE: If user selected a specific developer preset, you MUST use that technology and ONLY that technology.\n"
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
            "3. content field: describe WHAT to implement (not actual code)\n"
            "4. NO MIXING technologies (if user wants X, don't add Y)\n"
            "5. CRITICAL: NEVER use .txt files. For notes/docs use .md ONLY. For LaTeX use .tex ONLY.\n"
            "   If you need plain text notes, still use .md.\n"
            "6. 🚨 IF USER SELECTED PYTHON DEVELOPER: tech_stack MUST be 'python', files MUST be .py ONLY\n"
            "   - NO index.html, NO script.js, NO style.css, NO package.json\n"
            "   - ONLY .py files (main.py, requirements.txt, README.md for docs)\n"
            "7. 🚨 IF USER SELECTED C++ DEVELOPER: tech_stack MUST be 'cpp', files MUST be .cpp/.h ONLY\n"
            "   - NO JavaScript, NO Python, NO web files\n"
            "   - ONLY .cpp, .h, CMakeLists.txt, Makefile, README.md\n"
            "8. Return ONLY JSON, no text before or after\n"
        )
        adapter = get_llm_adapter()
        
        # Rate limit handling (similar to DeveloperAgent)
        rate_limit_backoffs = [10, 20, 40]
        rate_limit_attempt = 0
        
        def _is_rate_limit_error(exc: Exception) -> bool:
            try:
                from tenacity import RetryError  # type: ignore[import-not-found]
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
            # #region agent log
            with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
                import json as json_lib, time
                f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"ceo.py:101","message":"CEO calling LLM adapter","data":{"llm_mode":settings.llm_mode,"prompt_length":len(prompt)},"timestamp":int(time.time()*1000)}) + '\n')
            # #endregion
            LOGGER.info("CEO calling LLM adapter (mode=%s)...", settings.llm_mode)
            
            while True:
                try:
                    # #region agent log
                    with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
                        import json as json_lib, time
                        f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"ceo.py:105","message":"CEO before adapter.acomplete","data":{"rate_limit_attempt":rate_limit_attempt},"timestamp":int(time.time()*1000)}) + '\n')
                    # #endregion
                    response = await adapter.acomplete(prompt, json_mode=True)
                    # #region agent log
                    with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
                        import json as json_lib, time
                        f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"ceo.py:110","message":"CEO after adapter.acomplete","data":{"response_length":len(response or "")},"timestamp":int(time.time()*1000)}) + '\n')
                    # #endregion
                    break  # Success
                except Exception as exc:
                    # #region agent log
                    with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
                        import json as json_lib, time
                        f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"ceo.py:114","message":"CEO exception in adapter.acomplete","data":{"exc_type":type(exc).__name__,"exc_msg":str(exc)[:200],"is_rate_limit":_is_rate_limit_error(exc)},"timestamp":int(time.time()*1000)}) + '\n')
                    # #endregion
                    if _is_rate_limit_error(exc) and rate_limit_attempt < len(rate_limit_backoffs):
                        wait_s = rate_limit_backoffs[rate_limit_attempt]
                        rate_limit_attempt += 1
                        LOGGER.warning("CEO rate limit hit, waiting %ds...", wait_s)
                        await asyncio.sleep(wait_s)
                        continue
                    raise
            
            LOGGER.info("CEO received plan response (length=%d chars)", len(response or ""))
            
            # Parse response
            if not response or not response.strip():
                # #region agent log
                with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
                    import json as json_lib, time
                    f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"ceo.py:120","message":"CEO empty response","data":{},"timestamp":int(time.time()*1000)}) + '\n')
                # #endregion
                raise ValueError("CEO received empty response from LLM")
            
            LOGGER.debug("CEO parsing JSON response...")
            # #region agent log
            with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
                import json as json_lib, time
                f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"ceo.py:125","message":"CEO before json.loads","data":{"response_preview":response[:100] if response else ""},"timestamp":int(time.time()*1000)}) + '\n')
            # #endregion
            data = json.loads(response)
            LOGGER.debug("CEO parsed JSON successfully")
            
            # Handle Thought Streaming if present
            if "_thought" in data:
                # Ideally we would broadcast this, but CEO doesn't have WS manager context yet.
                # We'll log it for now.
                LOGGER.info("CEO Thought: %s", data["_thought"])
                
            steps = data.get("steps", [])
            if isinstance(data, list): # Fallback if LLM returned list directly
                steps = data

            # Ensure IDs and validate step count
            for step in steps:
                if "id" not in step:
                    step["id"] = str(uuid4())
            
            # Validate step range (5-8 for quality)
            if len(steps) > 10:
                LOGGER.warning("CEO created %d steps (too many), limiting to 8", len(steps))
                steps = steps[:8]
            elif len(steps) < 3:
                LOGGER.warning("CEO created only %d steps (too few), using fallback", len(steps))
                return self._mock_plan(description, target, persona_prompt=persona_prompt, agent_preset=agent_preset, research_results=research_results)
            
            LOGGER.info("CEO created %d steps for quality development", len(steps))
            if "_thought" in data:
                LOGGER.info("CEO reasoning: %s", data["_thought"][:200])
            # #region agent log
            with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
                import json as json_lib, time
                f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"ceo.py:150","message":"CEO returning plan","data":{"steps_count":len(steps)},"timestamp":int(time.time()*1000)}) + '\n')
            # #endregion
            return steps
        except Exception as exc:
            # #region agent log
            with open('/Users/sasii/Code/projects/.cursor/debug.log', 'a') as f:
                import json as json_lib, time
                f.write(json_lib.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"ceo.py:155","message":"CEO plan generation exception","data":{"exc_type":type(exc).__name__,"exc_msg":str(exc)[:300]},"timestamp":int(time.time()*1000)}) + '\n')
            # #endregion
            LOGGER.error("CEO plan generation failed: %s", exc, exc_info=True)
            # Fallback - detect stack from description and create appropriate plan
            return self._mock_plan(description, target, persona_prompt=persona_prompt, agent_preset=agent_preset, research_results=research_results)

    def _detect_stack_from_description(self, description: str, persona_prompt: str = "", agent_preset: str = "") -> str:
        """Detect tech stack from user's description, team composition, and agent preset."""
        # PRIORITY 1: Agent preset (highest priority - user explicitly selected)
        if agent_preset:
            preset_lower = agent_preset.lower()
            if "python" in preset_lower or "senior_python" in preset_lower:
                return 'python'
            if "cpp" in preset_lower or "c++" in preset_lower or "senior_cpp" in preset_lower:
                return 'cpp'
            if "typescript" in preset_lower or "fullstack_ts" in preset_lower:
                return 'typescript'
        
        # PRIORITY 2: Team composition
        if persona_prompt:
            tech_hints = self._extract_tech_hints_from_team(persona_prompt)
            if tech_hints["has_cpp"]:
                return 'cpp'
            if tech_hints["has_python"]:
                return 'python'
            if "typescript" in tech_hints["languages"]:
                return 'typescript'
        
        # PRIORITY 2: User's explicit request
        desc_lower = description.lower()
        
        # Check for explicit language mentions
        if any(word in desc_lower for word in ['c++', 'cpp', 'с++', 'плюс', 'g++', 'clang++']):
            return 'cpp'
        if any(word in desc_lower for word in ['rust', 'cargo', 'раст']):
            return 'rust'
        if any(word in desc_lower for word in ['go ', 'golang', 'го ']):
            return 'go'
        if any(word in desc_lower for word in ['java ', 'jdk', 'maven', 'gradle', 'джава']):
            return 'java'
        if any(word in desc_lower for word in ['c#', 'csharp', 'dotnet', '.net', 'шарп']):
            return 'csharp'
        if any(word in desc_lower for word in ['python', 'питон', 'py ', 'django', 'flask', 'fastapi']):
            return 'python'
        if any(word in desc_lower for word in ['react', 'реакт', 'jsx', 'tsx', 'next.js']):
            return 'react'
        if any(word in desc_lower for word in ['javascript', 'js ', 'node', 'typescript', 'ts ']):
            return 'vanilla'
        if any(word in desc_lower for word in ['web', 'html', 'сайт', 'website']):
            return 'vanilla'
        
        # Default based on target
        return 'python' if 'api' in desc_lower else 'vanilla'

    def _mock_plan(
        self,
        description: str,
        target: str,
        persona_prompt: str = "",
        agent_preset: str = "",
        research_results: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        """Create a plan based on detected tech stack and team composition."""
        # Use agent_preset as highest priority for tech stack detection
        tech_stack = self._detect_stack_from_description(description, persona_prompt=persona_prompt, agent_preset=agent_preset)
        tech_hints = self._extract_tech_hints_from_team(persona_prompt)
        
        # Override with agent_preset if set
        if agent_preset:
            preset_lower = agent_preset.lower()
            if "python" in preset_lower or "senior_python" in preset_lower:
                tech_stack = "python"
                tech_hints["has_python"] = True
                tech_hints["has_cpp"] = False
            elif "cpp" in preset_lower or "c++" in preset_lower or "senior_cpp" in preset_lower:
                tech_stack = "cpp"
                tech_hints["has_cpp"] = True
                tech_hints["has_python"] = False
            elif "typescript" in preset_lower or "fullstack_ts" in preset_lower:
                tech_stack = "typescript"
                tech_hints["has_python"] = False
                tech_hints["has_cpp"] = False
        LOGGER.info("Mock plan using detected stack: %s", tech_stack)
        
        # Stack-specific file templates
        if tech_stack == 'cpp':
            files_setup = [
                {"path": "Makefile", "content": f"Build rules for: {description}"},
                {"path": "main.cpp", "content": f"Entry point for: {description}. Implement the main function."},
            ]
            files_core = [
                {"path": "solution.hpp", "content": f"Header with class/function declarations for: {description}"},
                {"path": "solution.cpp", "content": f"Implementation of: {description}"},
            ]
        elif tech_stack == 'python':
            files_setup = [
                {"path": "requirements.txt", "content": "Dependencies for the project"},
                {"path": "main.py", "content": f"Entry point for: {description}"},
            ]
            files_core = [
                {"path": "core.py", "content": f"Core implementation of: {description}"},
            ]
        elif tech_stack == 'rust':
            files_setup = [
                {"path": "Cargo.toml", "content": f"Rust project config for: {description}"},
                {"path": "src/main.rs", "content": f"Entry point for: {description}"},
            ]
            files_core = [
                {"path": "src/lib.rs", "content": f"Library implementation of: {description}"},
            ]
        elif tech_stack == 'go':
            files_setup = [
                {"path": "go.mod", "content": f"Go module for: {description}"},
                {"path": "main.go", "content": f"Entry point for: {description}"},
            ]
            files_core = [
                {"path": "solution.go", "content": f"Implementation of: {description}"},
            ]
        elif tech_stack == 'java':
            files_setup = [
                {"path": "pom.xml", "content": f"Maven config for: {description}"},
                {"path": "src/main/java/Main.java", "content": f"Entry point for: {description}"},
            ]
            files_core = [
                {"path": "src/main/java/Solution.java", "content": f"Implementation of: {description}"},
            ]
        elif tech_stack == 'csharp':
            files_setup = [
                {"path": "Project.csproj", "content": f".NET project for: {description}"},
                {"path": "Program.cs", "content": f"Entry point for: {description}"},
            ]
            files_core = [
                {"path": "Solution.cs", "content": f"Implementation of: {description}"},
            ]
        elif tech_stack == 'typescript':
            files_setup = [
                {"path": "package.json", "content": f"Node.js project config for: {description}"},
                {"path": "tsconfig.json", "content": "TypeScript configuration"},
                {"path": "src/index.ts", "content": f"Entry point for: {description}"},
            ]
            files_core = [
                {"path": "src/core.ts", "content": f"Core implementation of: {description}"},
            ]
        else:  # vanilla/web
            files_setup = [
                {"path": "index.html", "content": f"HTML for: {description}"},
                {"path": "style.css", "content": "Styles"},
                {"path": "script.js", "content": f"JavaScript for: {description}"},
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
        
        # Documentation step - use team's format if available
        doc_files = []
        doc_agent = "developer"  # default
        doc_format = "markdown"
        
        if tech_hints["has_latex"]:
            doc_files = [
                {"path": "documentation.tex", "content": f"LaTeX documentation for: {description}\n\nUse \\documentclass{{article}}, proper sections, and math mode if needed."},
            ]
            doc_agent = "writer"
            doc_format = "latex"
        elif tech_hints["has_technical_writer"]:
            doc_files = [
                {"path": "README.md", "content": f"# {description}\n\nDocumentation and usage instructions."},
            ]
            doc_agent = "writer"
            doc_format = "markdown"
        else:
            # Default: simple README
            doc_files = [
                {"path": "README.md", "content": f"# {description}\n\nDocumentation and usage instructions."},
            ]
        
        if doc_files:
            steps.append({
                "id": str(uuid4()),
                "name": "docs",
                "agent": doc_agent,
                "parallel_group": None,
                "payload": {
                    "tech_stack": doc_format,
                    "files": doc_files,
                },
            })
        
        return steps
