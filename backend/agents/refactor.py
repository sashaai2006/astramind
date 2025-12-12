from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from backend.core.event_bus import emit_event
from backend.llm.adapter import get_llm_adapter
from backend.memory import utils as db_utils
from backend.memory.db import get_session
from backend.memory.vector_store import get_project_memory, get_semantic_cache
from backend.settings import get_settings
from backend.utils.fileutils import write_files, iter_file_entries, read_project_file
from backend.utils.json_parser import clean_and_parse_json
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)

class RefactorAgent:

    def __init__(self) -> None:
        self._adapter = get_llm_adapter()
        self._settings = get_settings()

    async def _broadcast_thought(self, project_id: str, msg: str, level: str = "info"):
        # Don't await - fire and forget to avoid blocking
        import asyncio
        asyncio.create_task(
            emit_event(project_id, msg, agent="refactor", level=level, persist=False)
        )

    async def chat(self, project_id: UUID, message: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        project_path = self._settings.projects_root / str(project_id)
        if not project_path.exists():
            return "Project not found."

        # Detect intent from natural language
        intent = self._detect_intent(message)
        await self._broadcast_thought(str(project_id), f"Understanding request: {intent}...")

        context_files = self._read_context_files(project_path, user_query=message)
        await self._broadcast_thought(str(project_id), "Reading relevant files...")
        
        # 🧠 Получаем релевантный контекст из долгосрочной памяти
        memory_context = ""
        try:
            memory = get_project_memory(str(project_id))
            memory_context = memory.get_relevant_context(message, max_chars=1500)
            if memory_context:
                await self._broadcast_thought(str(project_id), "🧠 Found relevant context in memory")
        except Exception as e:
            LOGGER.warning("Failed to load memory context in refactor: %s", e)
            # Продолжаем без памяти
        
        prompt = self._build_chat_prompt(message, context_files, history or [], intent, memory_context)

        LOGGER.info("RefactorAgent calling LLM for project %s", project_id)
        await self._broadcast_thought(str(project_id), "Thinking about your request...")
        
        # Try with JSON mode first
        max_retries = 2
        updates = None
        last_error = None
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
        
        for attempt in range(max_retries):
            try:
                # Use native JSON mode if available
                response = await self._adapter.acomplete(prompt, json_mode=True)
                
                LOGGER.info("RefactorAgent attempt %d: raw response length: %d", attempt + 1, len(response))
                LOGGER.info("RefactorAgent raw response start: %s", response[:500])

                updates = clean_and_parse_json(response)
                if not isinstance(updates, dict):
                    raise ValueError("Parsed JSON is not a dictionary")
                
                # Success!
                break
                
            except Exception as exc:
                last_error = exc
                LOGGER.warning("RefactorAgent attempt %d failed: %s", attempt + 1, exc)

                # Provider rate-limit: cooldown and retry without rewriting the prompt
                if _is_rate_limit_error(exc) and rate_limit_attempt < len(rate_limit_backoffs):
                    wait_s = rate_limit_backoffs[rate_limit_attempt]
                    rate_limit_attempt += 1
                    await self._broadcast_thought(str(project_id), f"Rate limit hit. Cooling down for {wait_s}s…", "warning")
                    import asyncio
                    await asyncio.sleep(wait_s)
                    continue
                
                if attempt < max_retries - 1:
                    # Retry with a stricter prompt
                    await self._broadcast_thought(str(project_id), f"Retrying (attempt {attempt + 2}/{max_retries})...", "warning")
                    prompt = (
                        "CRITICAL ERROR: Your previous response was not valid JSON.\n"
                        "You MUST respond with ONLY a JSON object. No text before or after.\n"
                        "Start with { and end with }.\n"
                        "\n"
                        f"Original request: {message}\n"
                        "\n"
                        "Respond ONLY with this exact structure:\n"
                        '{\n'
                        '  "_thought": "your reasoning here",\n'
                        '  "message": "brief summary",\n'
                        '  "files": [{"path": "...", "content": "..."}]\n'
                        '}\n'
                    )
        
        if updates is None:
            LOGGER.error("RefactorAgent failed after %d attempts: %s", max_retries, last_error)
            await self._broadcast_thought(str(project_id), f"Failed to get valid response from AI", "error")
            return (
                "I'm having trouble understanding the request. "
                "Could you rephrase it more specifically? "
                "For example: 'Add error handling to index.py' or 'Create a new file utils.js with helper functions'."
            )

        # Log thought if present (Chain-of-Thought)
        if "_thought" in updates:
            thought = updates["_thought"]
            await self._broadcast_thought(str(project_id), f"Thought: {thought}", "info")

        files_to_update = self._normalize_files(updates.get("files"))
        response_message = updates.get("message", "Done.")

        if not files_to_update:
            LOGGER.warning("RefactorAgent returned no files to update. Message: %s", response_message)
            await self._broadcast_thought(str(project_id), "No file changes proposed.", "warning")
        
        if files_to_update:
            try:
                await self._broadcast_thought(str(project_id), f"Applying changes to {len(files_to_update)} files...")
                # Resolve to absolute path to avoid relative/absolute path conflicts
                project_root = project_path.resolve()
                saved = write_files(project_root, files_to_update)
                # Update artifacts in DB
                sizes = [s.stat().st_size for s in saved]
                relative_paths = [s.relative_to(project_root).as_posix() for s in saved]
                
                async with get_session() as session:
                    await db_utils.add_artifacts(
                        session, project_id, relative_paths, sizes
                    )
                    await db_utils.record_event(
                        session,
                        project_id,
                        f"Refactor applied: {len(saved)} files changed",
                        agent="refactor",
                    )
                
                # 🧠 Сохраняем в долгосрочную память
                try:
                    memory = get_project_memory(str(project_id))
                    for file_def in files_to_update:
                        path = file_def.get("path", "")
                        content = file_def.get("content", "")
                        if content and len(content) < 10000:
                            memory.add_file(path, content)
                    
                    # Сохраняем решение агента
                    thought = updates.get("_thought", "")
                    if thought:
                        memory.add_decision(
                            decision=f"Refactored: {message[:100]}",
                            reasoning=thought
                        )
                except Exception as e:
                    LOGGER.warning("Failed to save to memory in refactor: %s", e)
                    # Продолжаем без сохранения в память

                # Notify frontend
                for rel_path in relative_paths:
                    await emit_event(
                        str(project_id),
                        f"Updated {rel_path}",
                        agent="refactor",
                        data={"artifact_path": rel_path},
                        persist=False,
                    )
                
                if "modified" not in response_message.lower() and "created" not in response_message.lower():
                    response_message += f"\n(Updated {len(saved)} files)"
            
            except Exception as e:
                LOGGER.error("Failed to write files: %s", e)
                await self._broadcast_thought(str(project_id), f"Error writing files: {e}", "error")
                return f"Error writing files: {e}"

        return response_message

    def _read_context_files(self, project_path: Path, user_query: str = "") -> str:
        entries = list(iter_file_entries(project_path))[:30]  # Limit to first 30 files for speed
        
        # Scoring function
        def score_entry(entry):
            score = 0
            path_str = entry.path.lower()
            query_terms = user_query.lower().split()
            
            # Match terms in query (high priority)
            for term in query_terms:
                if len(term) > 3 and term in path_str:
                    score += 20  # Increased from 10
            
            # Prioritize source code
            if path_str.endswith(('.py', '.tsx', '.ts', '.js', '.jsx', '.html', '.css', '.cs', '.cpp', '.c', '.h', '.hpp', '.rs', '.go', '.java', '.php', '.rb')):
                score += 5
            elif path_str.endswith('.json') or path_str.endswith('.md'):
                score += 1  # Reduced from 2
            else:
                score -= 10  # Increased penalty for irrelevant files
                
            # Strong penalty for size
            if entry.size_bytes > 5000:  # Reduced threshold
                score -= 5
            if entry.size_bytes > 20000:  # More aggressive
                score -= 20
                
            return score

        # Sort by score descending
        sorted_entries = sorted(entries, key=score_entry, reverse=True)
        
        buffer = []
        total_chars = 0
        MAX_CHARS = 8000  # ULTRA reduced for speed
        MAX_FILES = 3  # Only 3 most relevant files

        files_included = 0
        for entry in sorted_entries:
            if entry.is_dir:
                continue
            
            if files_included >= MAX_FILES:
                break
            
            # Hard skip large files (aggressive)
            if entry.size_bytes > 20000:  # Very aggressive filtering
                continue
            
            # Skip low-score files entirely
            if score_entry(entry) < 0:
                continue
            
            try:
                content, is_text = read_project_file(project_path, entry.path)
                if is_text:
                    text = content.decode("utf-8")
                    
                    # Skip map files and lock files content unless explicitly asked
                    if ("lock" in entry.path or entry.path.endswith(".map") or "node_modules" in entry.path):
                        continue

                    if total_chars + len(text) > MAX_CHARS:
                        # Truncate instead of skipping completely
                        remaining = MAX_CHARS - total_chars
                        if remaining > 500:  # At least show something
                            buffer.append(f"--- FILE: {entry.path} (truncated) ---\n{text[:remaining]}...")
                            files_included += 1
                        break
                    else:
                        buffer.append(f"--- FILE: {entry.path} ---\n{text}")
                        total_chars += len(text)
                        files_included += 1
            except Exception:
                pass
        
        if not buffer:
            return "--- No relevant files found in project ---"
        
        return "\n\n".join(buffer)

    def _detect_intent(self, message: str) -> str:
        msg_lower = message.lower()
        
        # Convert/Rewrite intent
        if any(word in msg_lower for word in ['перепиши', 'rewrite', 'convert', 'change to', 'make it', 'в c#', 'на c#', 'to c#', 'in c#']):
            # Detect target language
            if 'c#' in msg_lower or 'csharp' in msg_lower:
                return "convert to C#"
            elif 'python' in msg_lower or 'py' in msg_lower:
                return "convert to Python"
            elif 'java' in msg_lower:
                return "convert to Java"
            elif 'go' in msg_lower or 'golang' in msg_lower:
                return "convert to Go"
            elif 'rust' in msg_lower:
                return "convert to Rust"
            else:
                return "refactor code"
        
        # Fix/Debug intent
        if any(word in msg_lower for word in ['fix', 'исправь', 'debug', 'ошибка', 'error', 'bug', 'broken', 'не работает']):
            return "fix bugs"
        
        # Optimize intent
        if any(word in msg_lower for word in ['optimize', 'faster', 'speed', 'performance', 'оптимизируй', 'ускорь']):
            return "optimize code"
        
        # Explain intent
        if any(word in msg_lower for word in ['explain', 'what', 'how', 'why', 'объясни', 'как работает', 'что делает']):
            return "explain code"
        
        # Add feature intent
        if any(word in msg_lower for word in ['add', 'create', 'new', 'добавь', 'создай', 'сделай']):
            return "add new feature"
        
        # Test intent
        if any(word in msg_lower for word in ['test', 'tests', 'unit test', 'тест']):
            return "add tests"
        
        # Document intent
        if any(word in msg_lower for word in ['document', 'docs', 'comment', 'документ', 'комментарий']):
            return "add documentation"
        
        # Default
        return "modify code"

    def _build_chat_prompt(self, user_message: str, context_files: str, history: List[Dict[str, str]], intent: str = "modify code", memory_context: str = "") -> str:
        history_text = ""
        if history:
            history_text = "Previous Conversation:\n"
            for msg in history[-5:]:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                history_text += f"{'User' if role == 'user' else 'You'}: {content}\n"
            history_text += "\n"
        
        # 🧠 Добавляем контекст из долгосрочной памяти
        memory_section = ""
        if memory_context:
            memory_section = (
                "**Relevant Context from Project Memory (previous decisions/files):**\n"
                f"{memory_context}\n\n"
            )

        # Build intent-specific guidance
        intent_guidance = {
            "convert to C#": "Convert code to C# (.cs files). Use proper namespaces and classes.",
            "convert to Python": "Convert code to Python (.py files). Follow PEP 8.",
            "convert to Java": "Convert code to Java (.java files). One public class per file.",
            "convert to Go": "Convert code to Go (.go files). Use 'package main'.",
            "convert to Rust": "Convert code to Rust (.rs files). Use idiomatic Rust.",
            "fix bugs": "Analyze code for syntax/logic errors and fix them. Keep original language.",
            "optimize code": "Improve performance, remove redundant code, use better algorithms",
            "explain code": "Return detailed explanation in 'message' field. Set 'files' to empty array [].",
            "add new feature": "Create new files or modify existing ones to add the requested functionality",
            "add tests": "Create test files (e.g., test_*.py, *_test.go, *.test.js) with unit tests",
            "add documentation": "Add comments, docstrings, and README updates",
        }
        
        guidance = intent_guidance.get(intent, "Understand the request and make appropriate changes suitable for the existing tech stack.")

        return (
            "You are a LEGENDARY SOFTWARE ENGINEER with 20 years experience.\n"
            "You have mastered Computer Science and can work with ANY technology.\n"
            "You write PRODUCTION-READY code that COMPILES and RUNS.\n"
            "\n"
            f"=== USER REQUEST ===\n"
            f"Intent: {intent}\n"
            f"Mission: {guidance}\n"
            f'Message: "{user_message}"\n'
            "\n"
            f"{memory_section}"
            f"=== PROJECT FILES ===\n{context_files}\n\n"
            f"{history_text}"
            "=== CODE QUALITY STANDARDS ===\n"
            "1. COMPLETE: Every function fully implemented, no stubs\n"
            "2. CORRECT: Code must compile/parse and run\n"
            "3. CLEAN: Readable, well-structured, good names\n"
            "4. IDIOMATIC: Follow conventions of the target language\n"
            "\n"
            "=== BEFORE SUBMITTING ===\n"
            "✓ All dependencies declared?\n"
            "✓ Entry point exists?\n"
            "✓ Syntax is valid?\n"
            "✓ Would it run if executed?\n"
            "\n"
            "=== OUTPUT (JSON) ===\n"
            "{\n"
            '  "_thought": "Analysis: User wants X. I will do Y.",\n'
            '  "message": "Friendly response to user",\n'
            '  "files": [\n'
            '    {"path": "file.ext", "content": "COMPLETE CODE with \\\\n for newlines"}\n'
            '  ]\n'
            "}\n"
            "\n"
            "=== RULES ===\n"
            "• content = COMPLETE file (not snippet)\n"
            "• Newlines → \\n, Quotes → \\\"\n"
            "• No markdown inside JSON\n"
            "• If just explaining, files = []\n"
            "\n"
            "START WITH { END WITH } - NO OTHER TEXT!"
        )

    def _normalize_files(self, files: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
        if not files:
            return []

        normalized: List[Dict[str, str]] = []
        for file in files:
            path_value = file.get("path")
            content_value = file.get("content", "")

            if not path_value or not isinstance(path_value, str):
                LOGGER.warning("RefactorAgent skipping file without valid path: %s", file)
                continue

            safe_path = path_value.strip()
            if not safe_path or ".." in Path(safe_path).parts:
                LOGGER.warning("RefactorAgent skipping unsafe path: %s", path_value)
                continue

            if isinstance(content_value, (dict, list)):
                content_str = json.dumps(content_value, indent=2)
            else:
                content_str = str(content_value)

            normalized.append({"path": safe_path, "content": content_str})

        return normalized
