from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from backend.core.event_bus import emit_event
from backend.llm.adapter import get_llm_adapter
from backend.memory import utils as db_utils
from backend.memory.db import get_session
from backend.memory.vector_store import get_project_memory, get_semantic_cache
from backend.memory.knowledge_sources import get_knowledge_registry
from backend.settings import get_settings
from backend.utils.fileutils import write_files_async
from backend.utils.json_parser import clean_and_parse_json
from backend.utils.logging import get_logger
from backend.utils.path_normalizer import normalize_artifact_path

LOGGER = get_logger(__name__)

# Глобальный семантический кэш
_semantic_cache = None

def _get_cache():
    global _semantic_cache
    if _semantic_cache is None:
        _semantic_cache = get_semantic_cache()
    return _semantic_cache


class DeveloperAgent:
    """Transforms LLM JSON instructions into tangible project files."""

    def __init__(self, llm_semaphore) -> None:
        self._adapter = get_llm_adapter()
        self._settings = get_settings()
        self._semaphore = llm_semaphore

    async def _broadcast_thought(self, project_id: str, msg: str, level: str = "info", agent: str = "developer"):
        """Helper to broadcast agent thoughts to the UI."""
        # Keep "thoughts" WS-only to avoid DB write amplification
        await emit_event(project_id, msg, agent=agent, level=level, persist=False)

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
        # Add timeout per file (120s max) to prevent hanging on rate limits
        async def _generate_with_timeout(spec: Dict[str, Any]) -> Any:
            path_hint = normalize_artifact_path(spec.get("path", "unknown"))
            try:
                return await asyncio.wait_for(
                    self._generate_single_file(spec, context, step, stop_event),
                    timeout=120.0
                )
            except asyncio.TimeoutError:
                LOGGER.error("Timeout generating %s (exceeded 120s)", path_hint)
                raise RuntimeError(f"Timeout generating {path_hint} (exceeded 120s)")

        tasks = [
            _generate_with_timeout(spec)
            for spec in files_spec
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        file_defs: List[Dict[str, str]] = []
        had_errors = False
        for spec, result in zip(files_spec, results):
            if isinstance(result, Exception):
                path_value = normalize_artifact_path(spec.get("path", "unknown_artifact.txt"))
                error_msg = str(result)
                # Extract more useful error info
                if "RateLimitError" in error_msg or "rate limit" in error_msg.lower():
                    error_msg = "Rate limit exceeded. Please wait a moment and try again."
                elif "Timeout" in error_msg:
                    error_msg = f"Timeout generating {path_value} (took >120s)"
                
                LOGGER.error("DeveloperAgent error for %s: %s", path_value, result, exc_info=True)
                await self._broadcast_thought(
                    project_id,
                    f"Failed to generate {path_value}: {error_msg}",
                    "error",
                )
                had_errors = True
            else:
                file_defs.append(result)
                LOGGER.info("DeveloperAgent successfully generated: %s", result.get("path", "unknown"))

        # Quality-first: if any requested file failed, abort the step rather than writing placeholders.
        if had_errors:
            raise RuntimeError("One or more files failed to generate; aborting step to preserve quality.")

        # Auto-review critical files for quality
        critical_files = [f for f in file_defs if self._is_critical_file(f["path"])]
        if critical_files and len(critical_files) <= 2:  # Only if 1-2 critical files (don't spam)
            await self._broadcast_thought(project_id, f"Running quality check on {len(critical_files)} critical file(s)...")
            try:
                from backend.agents.reviewer import ReviewerAgent
                reviewer = ReviewerAgent()  # No args needed
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

    async def auto_correct(
        self,
        context: Dict[str, Any],
        issues: List[str],
        stop_event: asyncio.Event,
    ) -> None:
        """Attempt to fix the code based on tester issues."""
        if stop_event.is_set():
            return

        project_id = context["project_id"]
        await self._broadcast_thought(project_id, "Attempting to auto-correct issues...", "info")
        
        # Filter out non-critical issues (missing dependencies, style issues, etc.)
        critical_issues = []
        ignored_patterns = [
            "missing module", "ModuleNotFoundError", "No module named",
            "TODO", "FIXME", "placeholder", "stub", "optimization",
            "style", "documentation", "comment", "warning"
        ]
        
        for issue in issues:
            issue_lower = issue.lower()
            # Only include issues that are likely fixable and critical
            if not any(pattern in issue_lower for pattern in ignored_patterns):
                critical_issues.append(issue)
        
        if not critical_issues:
            await self._broadcast_thought(
                project_id, 
                "No critical issues to fix (only style/dependency warnings).", 
                "info"
            )
            return
        
        LOGGER.info("Auto-correcting %d critical issues (filtered from %d total)", len(critical_issues), len(issues))
        
        # Read all files to give full context
        project_context = await self._read_project_context(project_id)
        
        prompt = (
            "You are a senior developer fixing CRITICAL bugs in a project.\n"
            f"Project: {context['title']}\n"
            f"Description: {context['description']}\n"
            f"Tech Stack: {context.get('tech_stack', 'unknown')}\n"
            "\n"
            "EXISTING CODE:\n"
            f"{project_context}\n"
            "\n"
            "CRITICAL ISSUES TO FIX:\n"
            + "\n".join(f"- {issue}" for issue in critical_issues)
            + "\n\n"
            "INSTRUCTIONS:\n"
            "1. Analyze ONLY the critical issues listed above.\n"
            "2. Fix the issues by modifying the relevant files.\n"
            "3. Return the FULL content of ALL modified files (not just diffs).\n"
            "4. Ensure code compiles and has correct syntax.\n"
            "5. Output JSON format: {\"files\": [{\"path\": \"...\", \"content\": \"...\"}]}\n"
            "6. Only include files that you actually modified.\n"
            "7. Do not wrap the code in markdown blocks inside the JSON string.\n"
            "8. Make sure all imports are correct and functions are properly defined.\n"
            "\n"
            "IMPORTANT: If an issue cannot be fixed (e.g., missing external dependency), "
            "do not include it in the fixes. Only fix syntax errors, missing functions, and logic errors."
        )
        
        # Reuse _execute_with_retry to handle LLM call and parsing
        # We construct a dummy step for logging/tracking
        dummy_step = {"name": "auto_correct"}
        
        parsed_response = await self._execute_with_retry(prompt, dummy_step, context)
        
        if parsed_response and "files" in parsed_response:
            file_defs = self._normalize_files(parsed_response["files"], project_id)
            if file_defs:
                await self._save_files(project_id, dummy_step, file_defs)
                await self._broadcast_thought(project_id, f"Applied fixes to {len(file_defs)} files.", "success")
            else:
                await self._broadcast_thought(project_id, "LLM returned no files to fix.", "warning")
        else:
            await self._broadcast_thought(project_id, "Could not generate fixes.", "warning")

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
        path_value = normalize_artifact_path(spec.get("path", "unknown_artifact.txt"))

        # --- TURBO TEMPLATES START ---
        # Instant return for common config files
        turbo_content = self._get_turbo_template(path_value)
        if turbo_content:
            await self._broadcast_thought(project_id, f"Using Turbo Template for {path_value} (Instant)", "info")
            return {"path": path_value, "content": turbo_content}
        # --- TURBO TEMPLATES END ---

        # Log which file we're generating (helps debug hangs)
        await self._broadcast_thought(project_id, f"Generating {path_value}...", "info")
        LOGGER.info("DeveloperAgent generating file: %s", path_value)

        # Read project context (existing files) for better coherence
        project_context = await self._read_project_context(project_id)
        
        prompt = self._build_prompt(context, step, [spec], project_context=project_context)
        parsed_response = await self._execute_with_retry(prompt, step, context)
        
        if not parsed_response:
            error_msg = (
                f"LLM failed to generate {path_value} after all retries. "
                "This may be due to rate limits or API issues. "
                "Please check your API provider limits or try again later."
            )
            LOGGER.error(error_msg)
            raise RuntimeError(error_msg)
        
        file_defs = self._normalize_files(
            parsed_response.get("files") if parsed_response else [],
            project_id,
        )

        if not file_defs:
            error_msg = f"LLM returned no files for {path_value} (parsed_response had no 'files' key)"
            LOGGER.error(error_msg)
            raise RuntimeError(error_msg)

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
                    "allowJs": True,
                    "skipLibCheck": True,
                    "strict": True,
                    "forceConsistentCasingInFileNames": True,
                    "noEmit": True,
                    "esModuleInterop": True,
                    "module": "esnext",
                    "moduleResolution": "node",
                    "resolveJsonModule": True,
                    "isolatedModules": True,
                    "jsx": "preserve",
                    "incremental": True,
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
        """Save files to disk, record artifacts, and store in vector memory."""
        project_path = self._settings.projects_root / project_id
        project_path.mkdir(parents=True, exist_ok=True)
        project_root = project_path.resolve()
        
        await self._broadcast_thought(project_id, f"Writing {len(file_defs)} files to disk...")
        
        # Normalize paths (no .txt) before writing
        normalized_defs: List[Dict[str, str]] = [
            {"path": normalize_artifact_path(f.get("path", "")), "content": f.get("content", "")}
            for f in file_defs
        ]
        
        # Use async write
        saved = await write_files_async(project_path, normalized_defs)
        
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
        
        # 🧠 Сохраняем файлы в векторную память для долгосрочного контекста
        try:
            memory = get_project_memory(project_id)
            for file_def in normalized_defs:
                path = file_def.get("path", "")
                content = file_def.get("content", "")
                # Сохраняем только код (не слишком большие файлы)
                if content and len(content) < 10000:
                    memory.add_file(path, content)
        except Exception as e:
            LOGGER.warning("Failed to save files to memory: %s", e)
            # Продолжаем без сохранения в память

        # Batch event notifications (WS-only; avoid DB amplification)
        agent_name = step.get("agent", "developer")
        if relative_paths:
            await asyncio.gather(
                *(
                    emit_event(
                        project_id,
                        f"Artifact saved: {rel_path}",
                        agent=agent_name,
                        data={"artifact_path": rel_path},
                        persist=False,
                    )
                    for rel_path in relative_paths
                )
            )

    async def _execute_with_retry(self, prompt: str, step: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Execute LLM call with retries, repair logic, and semantic caching."""
        max_retries = 2
        current_prompt = prompt
        project_id = context["project_id"]
        rate_limit_backoffs = [10, 20, 40]  # seconds (in addition to adapter-level retries)
        rate_limit_attempt = 0

        def _is_rate_limit_error(exc: Exception) -> bool:
            # Avoid hard dependency on provider SDKs in agent layer.
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
        
        # Get tech_stack for cache key
        tech_stack = context.get("tech_stack") or step.get("payload", {}).get("tech_stack", "")
        
        # 1. SEMANTIC CACHE - DISABLED BY USER REQUEST
        # cache = _get_cache()
        # cache_filter = {"tech_stack": tech_stack} if tech_stack else None
        # ... (cache logic removed to prevent stale responses)
        
        # 2. Добавляем контекст из долгосрочной памяти (с обработкой ошибок)
        try:
            memory = get_project_memory(project_id)
            relevant_context = memory.get_relevant_context(
                f"{context.get('title', '')} {step.get('name', '')}",
                max_chars=2000
            )
            if relevant_context:
                current_prompt = f"{prompt}\n\n--- RELEVANT CONTEXT FROM MEMORY ---\n{relevant_context}"
                await self._broadcast_thought(project_id, "🧠 Found relevant context in memory", "info")
        except Exception as e:
            LOGGER.warning("Failed to load memory context: %s", e)
            # Продолжаем без памяти
        
        # 3. LLM Call with Retry Loop
        attempt = 0
        while attempt <= max_retries:
            step_name = step.get("name", "unknown")
            LOGGER.info(
                "Calling LLM adapter (mode=%s) for step '%s' (attempt %d/%d)",
                self._settings.llm_mode,
                step_name,
                attempt + 1,
                max_retries + 1,
            )
            
            if attempt > 0:
                await self._broadcast_thought(project_id, f"Retrying LLM generation (attempt {attempt + 1}/{max_retries + 1})...", "warning")

            try:
                LOGGER.debug("Acquiring semaphore for LLM call...")
                async with self._semaphore:
                    LOGGER.debug("Semaphore acquired, calling LLM adapter...")
                    completion = await self._adapter.acomplete(current_prompt, json_mode=True)
                    LOGGER.debug("LLM adapter returned (length=%d)", len(completion or ""))
            except Exception as exc:
                exc_name = exc.__class__.__name__
                exc_msg = str(exc)
                LOGGER.warning("LLM call failed: %s: %s", exc_name, exc_msg[:200])
                
                # If the provider exhausted its internal retries (tenacity RetryError), do a cooldown here.
                if _is_rate_limit_error(exc) and rate_limit_attempt < len(rate_limit_backoffs):
                    wait_s = rate_limit_backoffs[rate_limit_attempt]
                    rate_limit_attempt += 1
                    LOGGER.info("Rate limit detected, waiting %ds before retry...", wait_s)
                    await self._broadcast_thought(
                        project_id,
                        f"Rate limit hit. Cooling down for {wait_s}s and retrying…",
                        "warning",
                    )
                    await asyncio.sleep(wait_s)
                    # Retry same attempt (do not consume a JSON-repair retry)
                    continue
                
                # Re-raise to be handled by outer retry loop
                LOGGER.error("LLM call failed after rate-limit handling: %s", exc, exc_info=True)
                raise
            
            LOGGER.info("LLM response received (length=%d chars)", len(completion or ""))
            
            try:
                parsed = clean_and_parse_json(completion)
                if isinstance(parsed, dict) and "files" in parsed:
                    if "_thought" in parsed:
                        await self._broadcast_thought(project_id, f"Developer thought: {parsed['_thought']}", "info")
                    
                    # Save to cache - DISABLED
                    # try:
                    #     cache_meta = {"tech_stack": tech_stack} if tech_stack else None
                    #     cache.set(cache_key_prompt, completion, metadata=cache_meta)
                    # except Exception as e:
                    #     LOGGER.warning("Failed to cache response: %s", e)
                    
                    # Save decision to memory
                    try:
                        memory = get_project_memory(project_id)
                        memory.add_decision(
                            decision=f"Step '{step.get('name')}' completed",
                            reasoning=parsed.get("_thought", "")
                        )
                    except Exception as e:
                        LOGGER.warning("Failed to save decision to memory: %s", e)
                    
                    return parsed
                elif isinstance(parsed, list):
                    # cache.set(cache_key_prompt, completion) - DISABLED
                    return {"files": parsed}
                else:
                    raise ValueError("JSON is valid but does not contain 'files' or is not a list")
            except Exception as exc:
                LOGGER.warning("JSON parse failed on attempt %d: %s", attempt + 1, exc)
                if attempt < max_retries:
                    await self._broadcast_thought(project_id, "Received invalid JSON from LLM. Attempting auto-repair...", "warning")
                    # Keep original task context, then request a corrected JSON payload.
                    current_prompt = (
                        prompt
                        + "\n\n=== IMPORTANT: YOUR PREVIOUS RESPONSE WAS INVALID JSON ===\n"
                        + f"Error: {exc}\n"
                        + "Return ONLY valid JSON with a top-level 'files' array.\n"
                        + "Do NOT add any text before/after the JSON.\n"
                        + "\n--- Previous (invalid) response ---\n"
                        + completion[:3000]
                    )
                    attempt += 1
                    continue
        
        return None

    async def _read_project_context(self, project_id: str) -> str:
        """Read existing files in the project for context."""
        try:
            from backend.utils.fileutils import iter_file_entries, read_project_file
            
            project_path = self._settings.projects_root / project_id
            if not project_path.exists():
                return ""
            
            context_files = []
            max_files = 5  # Limit to avoid token overflow
            max_size = 2000  # Max chars per file
            
            for file_path in list(iter_file_entries(project_path))[:max_files]:
                try:
                    data, is_text = await asyncio.to_thread(read_project_file, project_path, file_path.path)
                    if is_text:
                        content = data.decode("utf-8")
                        if content and len(content) < max_size:
                            context_files.append(f"FILE: {file_path.path}\n```\n{content[:max_size]}\n```")
                except:
                    continue
        
            if context_files:
                return "\n\nEXISTING PROJECT FILES (for context):\n" + "\n\n".join(context_files)
            return ""
        except Exception as e:
            LOGGER.warning("Failed to read project context: %s", e)
            return ""

    def _build_prompt(
        self, 
        context: Dict[str, Any], 
        step: Dict[str, Any], 
        files_spec: List[Dict[str, Any]],
        feedback: List[str] = [],
        project_context: str = "",
        knowledge_context: str = "" # Added param
    ) -> str:
        from backend.agents.prompts import PromptBuilder
        return PromptBuilder.assemble_prompt(
            context,
            step,
            files_spec,
            feedback,
            project_context,
            knowledge_context
        )

    def _is_critical_file(self, path: str) -> bool:
        """Determine if a file is critical and should be auto-reviewed."""
        # Generic critical patterns for most languages
        critical_patterns = [
            "index.", "main.", "app.", "server.", "client.",  # Entry points
            "App.", "Program.", "setup.", "manage.",          # Framework entries
            "Cargo.toml", "package.json", "requirements.txt", # Configs
            "Makefile", "CMakeLists.txt", "pom.xml", "build.gradle"
        ]
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

            safe_path = normalize_artifact_path(path_value.strip())
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
            if len(content_str) > 400_000:
                LOGGER.error(
                    "DeveloperAgent received oversized content for %s (%d chars); skipping",
                    safe_path,
                    len(content_str),
                )
                continue

            # Ensure trailing newline for text artifacts (stabilizes diffs/tools)
            if content_str and not content_str.endswith("\n"):
                content_str += "\n"
            
            # Sanity check: content should not start with '{' unless it's JSON/JS object
            if content_str.startswith('{"') and not safe_path.endswith('.json'):
                LOGGER.warning(
                    "DeveloperAgent: content for %s starts with '{\"' which may indicate "
                    "LLM returned JSON object instead of code string",
                    safe_path
                )

            normalized.append({"path": safe_path, "content": content_str})

        return normalized
