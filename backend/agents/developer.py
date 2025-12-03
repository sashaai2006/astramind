from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from backend.core.ws_manager import ws_manager
from backend.llm.adapter import get_llm_adapter
from backend.memory import utils as db_utils
from backend.memory.db import get_session
from backend.settings import get_settings
from backend.utils.fileutils import write_files_async
from backend.utils.json_parser import clean_and_parse_json
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)


class DeveloperAgent:
    """Transforms LLM JSON instructions into tangible project files."""

    def __init__(self, llm_semaphore) -> None:
        self._adapter = get_llm_adapter()
        self._settings = get_settings()
        self._semaphore = llm_semaphore

    async def _broadcast_thought(self, project_id: str, msg: str, level: str = "info", agent: str = "developer"):
        """Helper to broadcast agent thoughts to the UI."""
        await ws_manager.broadcast(
            project_id,
            {
                "type": "event",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "agent": agent,
                "level": level,
                "msg": msg,
            },
        )

    async def run(
        self,
        step: Dict[str, Any],
        context: Dict[str, Any],
        stop_event,
        on_message: Optional[Any] = None,
    ) -> None:
        """Quality mode: generate code with optional review for critical files."""
        project_id = context["project_id"]
        if stop_event.is_set():
            LOGGER.info("Project %s stop requested; skipping step.", project_id)
            return

        step_name = step.get("name", "unknown")
        payload = step.get("payload", {})
        files_spec = payload.get("files", [])
        
        await self._broadcast_thought(project_id, f"Analyzing specs for step: {step_name}...")

        await self._broadcast_thought(project_id, "Generating high-quality code...")

        # Generate each file independently to avoid output token limits
        tasks = [
            self._generate_single_file(spec, context, step, stop_event)
            for spec in files_spec
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        file_defs: List[Dict[str, str]] = []
        for spec, result in zip(files_spec, results):
            if isinstance(result, Exception):
                path_value = spec.get("path", "unknown_artifact.txt")
                LOGGER.error("DeveloperAgent error for %s: %s", path_value, result)
                await self._broadcast_thought(
                    project_id,
                    f"Failed to generate {path_value}: {result}",
                    "error",
                )
                file_defs.append(
                    {
                        "path": path_value,
                        "content": f"// Failed to generate content for {path_value}.\n// Error: {result}",
                    }
                )
            else:
                file_defs.append(result)

        # Auto-review critical files for quality
        critical_files = [f for f in file_defs if self._is_critical_file(f["path"])]
        if critical_files and len(critical_files) <= 2:  # Only if 1-2 critical files (don't spam)
            await self._broadcast_thought(project_id, f"Running quality check on {len(critical_files)} critical file(s)...")
            try:
                from backend.agents.reviewer import ReviewerAgent
                reviewer = ReviewerAgent(self._semaphore)
                task_desc = f"{context['title']}: {step_name}"
                review_result = await reviewer.review(task_desc, critical_files)
                
                if not review_result["approved"]:
                    await self._broadcast_thought(
                        project_id,
                        f"Quality issues found in {critical_files[0]['path']}: {review_result['comments'][0] if review_result['comments'] else 'See logs'}",
                        "warning"
                    )
            except Exception as e:
                LOGGER.warning("Auto-review failed (non-critical): %s", e)

        await self._save_files(project_id, step, file_defs)
        
        if on_message:
             await on_message("ceo", "Task completed.")
             
        await self._broadcast_thought(project_id, f"Step '{step_name}' completed successfully.")

    async def _generate_single_file(
        self,
        spec: Dict[str, Any],
        context: Dict[str, Any],
        step: Dict[str, Any],
        stop_event,
    ) -> Dict[str, str]:
        """Generate a single file using the LLM or Turbo Templates."""
        if stop_event.is_set():
            raise asyncio.CancelledError()

        project_id = context["project_id"]
        path_value = spec.get("path", "unknown_artifact.txt")

        # --- TURBO TEMPLATES START ---
        # Instant return for common config files
        turbo_content = self._get_turbo_template(path_value)
        if turbo_content:
            await self._broadcast_thought(project_id, f"Using Turbo Template for {path_value} (Instant)", "info")
            return {"path": path_value, "content": turbo_content}
        # --- TURBO TEMPLATES END ---

        prompt = self._build_prompt(context, step, [spec])
        parsed_response = await self._execute_with_retry(prompt, step, context)
        file_defs = self._normalize_files(
            parsed_response.get("files") if parsed_response else [],
            project_id,
        )

        if not file_defs:
            raise RuntimeError(f"LLM returned no content for {path_value}")

        for file_def in file_defs:
            if file_def["path"] == path_value:
                return file_def
        return file_defs[0]

    def _get_turbo_template(self, path: str) -> Optional[str]:
        """Return pre-defined content for standard files."""
        p = Path(path)
        name = p.name
        
        # TS Config
        if name == "tsconfig.json":
            return json.dumps({
                "compilerOptions": {
                    "target": "es5",
                    "lib": ["dom", "dom.iterable", "esnext"],
                    "allowJs": true,
                    "skipLibCheck": true,
                    "strict": true,
                    "forceConsistentCasingInFileNames": true,
                    "noEmit": true,
                    "esModuleInterop": true,
                    "module": "esnext",
                    "moduleResolution": "node",
                    "resolveJsonModule": true,
                    "isolatedModules": true,
                    "jsx": "preserve",
                    "incremental": true,
                    "plugins": [{"name": "next"}],
                    "paths": {"@/*": ["./*"]}
                },
                "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
                "exclude": ["node_modules"]
            }, indent=2)

        # Gitignore
        if name == ".gitignore":
            return (
                "# dependencies\n/node_modules\n/.pnp\n.pnp.js\n\n"
                "# testing\n/coverage\n\n"
                "# next.js\n/.next/\n/out/\n\n"
                "# production\n/build\n\n"
                "# misc\n.DS_Store\n*.pem\n\n"
                "# debug\nnpm-debug.log*\nyarn-debug.log*\nyarn-error.log*\n\n"
                "# local env files\n.env*.local\n.env\n\n"
                "# vercel\n.vercel"
            )
            
        # PostCSS
        if name == "postcss.config.js":
            return 'module.exports = {\n  plugins: {\n    tailwindcss: {},\n    autoprefixer: {},\n  },\n}'

        # Tailwind Config
        if name in ["tailwind.config.ts", "tailwind.config.js"]:
            return (
                'import type { Config } from "tailwindcss";\n\n'
                'const config: Config = {\n'
                '  content: [\n'
                '    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",\n'
                '    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",\n'
                '    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",\n'
                '  ],\n'
                '  theme: {\n'
                '    extend: {\n'
                '      backgroundImage: {\n'
                '        "gradient-radial": "radial-gradient(var(--tw-gradient-stops))",\n'
                '        "gradient-conic": "conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))",\n'
                '      },\n'
                '    },\n'
                '  },\n'
                '  plugins: [],\n'
                '};\n'
                'export default config;'
            )

        # README (Generic)
        if name == "README.md":
            return (
                "# Generated Project\n\n"
                "This project was automatically generated by AstraMind AI.\n\n"
                "## Getting Started\n\n"
                "1. Install dependencies:\n   ```bash\n   npm install\n   # or\n   yarn install\n   ```\n\n"
                "2. Run the development server:\n   ```bash\n   npm run dev\n   # or\n   yarn dev\n   ```\n\n"
                "Open [http://localhost:3000](http://localhost:3000) with your browser to see the result."
            )
            
        # Next Config
        if name == "next.config.js":
            return '/** @type {import("next").NextConfig} */\nconst nextConfig = {\n  reactStrictMode: true,\n};\n\nmodule.exports = nextConfig;'

        # ESLint
        if name == ".eslintrc.json":
            return json.dumps({"extends": "next/core-web-vitals"}, indent=2)

        return None


    async def _save_files(self, project_id: str, step: Dict[str, Any], file_defs: List[Dict[str, str]]) -> None:
        """Save files to disk and record artifacts."""
        project_path = self._settings.projects_root / project_id
        project_path.mkdir(parents=True, exist_ok=True)
        project_root = project_path.resolve()
        
        await self._broadcast_thought(project_id, f"Writing {len(file_defs)} files to disk...")
        
        # Use async write
        saved = await write_files_async(project_path, file_defs)
        
        # Helper to get size async
        def get_file_info(path: Path, root: Path):
            return path.relative_to(root).as_posix(), path.stat().st_size

        # Run stats collection in thread pool
        file_infos = await asyncio.to_thread(
            lambda: [get_file_info(s, project_root) for s in saved]
        )
        
        relative_paths = [info[0] for info in file_infos]
        sizes = [info[1] for info in file_infos]

        async with get_session() as session:
            await db_utils.add_artifacts(
                session, UUID(project_id), relative_paths, sizes
            )

        # Batch WebSocket broadcasts using gather
        tasks = []
        timestamp = datetime.now(timezone.utc).isoformat()
        agent_name = step.get("agent", "developer")
        
        for rel_path in relative_paths:
            tasks.append(ws_manager.broadcast(
                project_id,
                {
                    "type": "event",
                    "timestamp": timestamp,
                    "project_id": project_id,
                    "agent": agent_name,
                    "level": "info",
                    "msg": f"Artifact saved: {rel_path}",
                    "artifact_path": rel_path,
                },
            ))
        
        if tasks:
            await asyncio.gather(*tasks)

    async def _execute_with_retry(self, prompt: str, step: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Execute LLM call with retries and repair logic."""
        max_retries = 2
        current_prompt = prompt
        project_id = context["project_id"]
        
        for attempt in range(max_retries + 1):
            LOGGER.info(
                "Calling LLM adapter (mode=%s) for step %s (attempt %d/%d)",
                self._settings.llm_mode,
                step.get("name"),
                attempt + 1,
                max_retries + 1
            )
            
            if attempt > 0:
                await self._broadcast_thought(project_id, f"Retrying LLM generation (attempt {attempt + 1}/{max_retries + 1})...", "warning")

            async with self._semaphore:
                completion = await self._adapter.acomplete(current_prompt, json_mode=True)
            
            LOGGER.info("LLM response received (length=%d)", len(completion))
            
            try:
                parsed = clean_and_parse_json(completion)
                if isinstance(parsed, dict) and "files" in parsed:
                    if "_thought" in parsed:
                        await self._broadcast_thought(project_id, f"Developer thought: {parsed['_thought']}", "info")
                    return parsed
                elif isinstance(parsed, list):
                    return {"files": parsed}
                else:
                    raise ValueError("JSON is valid but does not contain 'files' or is not a list")
            except Exception as exc:
                LOGGER.warning("JSON parse failed on attempt %d: %s", attempt + 1, exc)
                if attempt < max_retries:
                    await self._broadcast_thought(project_id, "Received invalid JSON from LLM. Attempting auto-repair...", "warning")
                    current_prompt = (
                        "The previous response was invalid JSON. Please fix it.\n"
                        f"Error: {exc}\n"
                        "Return ONLY valid JSON with 'files' array.\n"
                        "Previous response was:\n"
                        f"{completion[:2000]}" 
                    )
                    continue
        
        return None

    def _build_prompt(
        self, 
        context: Dict[str, Any], 
        step: Dict[str, Any], 
        files_spec: List[Dict[str, Any]],
        feedback: List[str] = []
    ) -> str:
        spec = json.dumps(files_spec, indent=2)
        feedback_section = ""
        if feedback:
            feedback_section = (
                "\nCRITICAL FEEDBACK FROM REVIEWER (You MUST fix these issues):\n"
                + "\n".join(f"- {f}" for f in feedback)
                + "\n"
            )

        return (
            "You are a SENIOR SOFTWARE DEVELOPER with 10+ years of experience.\n"
            f"Project: {context['title']} ({context['target']})\n"
            f"Full Description: {context['description']}\n"
            f"Current Task: {step.get('name')}\n"
            "\n"
            "CRITICAL: You must write COMPLETE, WORKING, PRODUCTION-READY code.\n"
            "Do NOT write placeholder comments like '// Add logic here' or '// TODO'.\n"
            "Do NOT write partial implementations.\n"
            "EVERY file must be fully functional and executable.\n"
            "\n"
            "Below are file specifications with natural language instructions.\n"
            "REPLACE the 'content' field with ACTUAL working code:\n"
            f"{spec}\n"
            f"{feedback_section}"
            "\n"
            "QUALITY REQUIREMENTS:\n"
            "1. COMPLETENESS: Write 100% of the code, not sketches or placeholders\n"
            "2. BEST PRACTICES: Use modern patterns, error handling, proper structure\n"
            "3. WORKING CODE: User should be able to run it immediately without modifications\n"
            "4. COMMENTS: Add brief comments only where logic is complex\n"
            "\n"
            "EXAMPLES OF BAD vs GOOD:\n"
            "❌ BAD: '// Implement snake movement logic here'\n"
            "✅ GOOD: Actual implementation with collision detection, boundary checks, state updates\n"
            "\n"
            "❌ BAD: '<canvas id=\"game\"></canvas>' (empty canvas)\n"
            "✅ GOOD: Canvas + full rendering code with requestAnimationFrame loop\n"
            "\n"
            "Output ONLY valid JSON. Format:\n"
            "{\n"
            '  "_thought": "Your step-by-step reasoning here",\n'
            '  "files": [\n'
            '    {\n'
            '      "path": "path/to/file.js",\n'
            '      "content": "THE ACTUAL CODE AS A STRING - use \\n for newlines, \\\\ for backslashes"\n'
            '    }\n'
            '  ]\n'
            "}\n"
            "\n"
            "CRITICAL RULES:\n"
            "1. The 'content' field MUST be a JSON STRING, not an object or array.\n"
            "2. All newlines in code must be escaped as \\n\n"
            "3. All quotes in code must be escaped as \\\"\n"
            "4. All backslashes must be escaped as \\\\\n"
            "5. Do NOT wrap code in curly braces - just put the raw code string.\n"
            "6. Do NOT include markdown formatting or code blocks.\n"
            "7. Return ONLY the JSON object, nothing else."
        )

    def _is_critical_file(self, path: str) -> bool:
        """Determine if a file is critical and should be auto-reviewed."""
        critical_patterns = ["index.html", "main.js", "main.py", "app.js", "game.js", "App.tsx", "index.tsx"]
        return any(pattern in path for pattern in critical_patterns)

    def _normalize_files(
        self, file_defs: Optional[List[Dict[str, Any]]], project_id: str
    ) -> List[Dict[str, str]]:
        if not file_defs:
            return []

        normalized: List[Dict[str, str]] = []

        for file in file_defs:
            path_value = file.get("path")
            content_value = file.get("content", "")

            if not path_value or not isinstance(path_value, str):
                LOGGER.warning("DeveloperAgent skipping file without valid path: %s", file)
                continue

            safe_path = path_value.strip()
            if not safe_path or ".." in Path(safe_path).parts:
                LOGGER.warning("DeveloperAgent skipping unsafe path: %s", path_value)
                continue

            # CRITICAL: content must be a string, not a dict/list
            # If LLM returns content as an object, it's an error
            if isinstance(content_value, (dict, list)):
                LOGGER.error(
                    "DeveloperAgent received content as object instead of string for %s. "
                    "This indicates LLM returned malformed JSON.",
                    safe_path
                )
                # Skip this file - it will trigger a retry or error stub
                continue

            content_str = str(content_value)
            
            # Sanity check: content should not start with '{' unless it's JSON/JS object
            if content_str.startswith('{"') and not safe_path.endswith('.json'):
                LOGGER.warning(
                    "DeveloperAgent: content for %s starts with '{\"' which may indicate "
                    "LLM returned JSON object instead of code string",
                    safe_path
                )

            normalized.append({"path": safe_path, "content": content_str})

        return normalized
