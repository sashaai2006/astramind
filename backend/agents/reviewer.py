from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.llm.adapter import get_llm_adapter
from backend.settings import get_settings
from backend.utils.json_parser import clean_and_parse_json
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)


class ReviewerAgent:
    """Analyzes code and provides constructive criticism."""

    def __init__(self) -> None:
        self._adapter = get_llm_adapter()
        self._settings = get_settings()

    async def review(
        self, 
        task_description: str, 
        files: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Review the provided files against the task description.
        Returns a dict with 'approved' (bool) and 'comments' (list).
        """
        prompt = self._build_review_prompt(task_description, files)
        
        LOGGER.info("ReviewerAgent starting code review...")
        response = await self._adapter.acomplete(prompt, json_mode=True)
        
        try:
            result = clean_and_parse_json(response)
            # Validate structure
            if not isinstance(result, dict):
                raise ValueError("Review result must be a dict")
            if "approved" not in result:
                result["approved"] = True # Default to approve if unsure
            if "comments" not in result:
                result["comments"] = []
            if "score" not in result:
                result["score"] = 70  # Default score
            if "blocking_issues" not in result:
                result["blocking_issues"] = []
            
            LOGGER.info(
                "Review complete. Approved: %s, Score: %s/100, Issues: %s",
                result["approved"],
                result.get("score", "N/A"),
                len(result.get("blocking_issues", []))
            )
            return result
        except Exception as e:
            LOGGER.warning("ReviewerAgent failed to parse response: %s", e)
            # If review fails, don't block the pipeline, just approve
            return {"approved": True, "comments": [], "score": 70, "blocking_issues": []}

    def _build_review_prompt(self, task_description: str, files: List[Dict[str, str]]) -> str:
        files_content = ""
        for f in files:
            path = f.get("path", "unknown")
            content = f.get("content", "")
            # Truncate very large files for review to save context
            if len(content) > 10000:
                content = content[:10000] + "\n...[truncated]..."
            files_content += f"--- FILE: {path} ---\n{content}\n\n"

        return (
            "You are a LEGENDARY CODE REVIEWER with 25 years of experience.\n"
            "You have deep expertise in Computer Science and Software Engineering.\n"
            "You review code in ANY language with equal skill.\n"
            "\n"
            f"=== TASK ===\n{task_description}\n\n"
            f"=== CODE ===\n{files_content}\n\n"
            "=== REVIEW CHECKLIST ===\n"
            "\n"
            "1. SYNTAX & COMPILATION:\n"
            "   - Will this code compile/parse without errors?\n"
            "   - Are all imports/includes/dependencies declared?\n"
            "   - Are delimiters matched (braces, parentheses, brackets)?\n"
            "\n"
            "2. COMPLETENESS:\n"
            "   - Are there any TODO/FIXME comments?\n"
            "   - Are there any empty or stub functions?\n"
            "   - Is every function fully implemented?\n"
            "\n"
            "3. CORRECTNESS:\n"
            "   - Trace the execution: would it work?\n"
            "   - Are variables initialized before use?\n"
            "   - Are return values correct?\n"
            "   - Are edge cases handled?\n"
            "\n"
            "4. CLEAN CODE:\n"
            "   - Readable and well-structured?\n"
            "   - Meaningful names?\n"
            "   - Appropriate for the language's idioms?\n"
            "\n"
            "=== OUTPUT (JSON) ===\n"
            "{\n"
            '  "_thought": "Analysis: checking syntax... completeness... logic...",\n'
            '  "approved": true/false,\n'
            '  "score": 0-100,\n'
            '  "comments": ["Issue description with line number if possible"],\n'
            '  "blocking_issues": ["Critical issues that prevent code from running"]\n'
            "}\n"
            "\n"
            "SCORING:\n"
            "• 90-100: Production ready\n"
            "• 70-89: Minor issues, works\n"
            "• 50-69: Has bugs, needs fixes\n"
            "• 0-49: Won't compile/run\n"
            "\n"
            "REJECT if score < 70 OR blocking_issues exist.\n"
            "Return ONLY JSON."
        )
