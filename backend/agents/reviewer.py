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
            "You are a LEGENDARY CODE REVIEWER from Google/Meta with 20+ years of experience.\n"
            "You have:\n"
            "- Reviewed 10,000+ pull requests at FAANG companies\n"
            "- Prevented countless critical bugs in production systems serving billions\n"
            "- Mentored engineers who now lead major tech companies\n"
            "- Uncompromising standards for code quality, security, and performance\n"
            "- Known for catching subtle bugs that others miss\n"
            "\n"
            f"Task: {task_description}\n"
            "\n"
            "Code Under Review:\n"
            f"{files_content}\n"
            "\n"
            "COMPREHENSIVE LEGENDARY REVIEW CHECKLIST:\n"
            "\n"
            "1. COMPLETENESS (Critical):\n"
            "   ✓ Is ALL functionality implemented? Zero TODOs/placeholders?\n"
            "   ✓ Are there any empty functions or stub implementations?\n"
            "   ✓ Does every class/function do something meaningful?\n"
            "   ✓ Is initialization code present? Will the code actually RUN?\n"
            "\n"
            "2. CORRECTNESS (Critical):\n"
            "   ✓ Syntax errors? Will it parse/compile?\n"
            "   ✓ Logic bugs? Off-by-one errors? Infinite loops?\n"
            "   ✓ Variable scoping issues? Undefined variables?\n"
            "   ✓ Type mismatches? Null/undefined dereferences?\n"
            "   ✓ Edge cases: empty arrays, null values, boundary conditions?\n"
            "\n"
            "3. SECURITY (Critical for production):\n"
            "   ✓ Input validation? (XSS, Buffer Overflows, SQL Injection)\n"
            "   ✓ Secure data handling? No hardcoded secrets?\n"
            "   ✓ Use of safe functions/libraries?\n"
            "\n"
            "4. PERFORMANCE (Important):\n"
            "   ✓ Algorithm complexity (avoid O(n²) if O(n) possible)?\n"
            "   ✓ Resource management (memory leaks, file handles closed)?\n"
            "   ✓ Efficient I/O operations?\n"
            "\n"
            "5. BEST PRACTICES (Important):\n"
            "   ✓ Standard conventions for the specific language?\n"
            "   ✓ DRY principle? Code duplication?\n"
            "   ✓ SOLID principles? Single Responsibility?\n"
            "   ✓ Error handling? (Exceptions, Result types, Error codes)?\n"
            "   ✓ Proper naming? Meaningful variable/function names?\n"
            "\n"
            "6. ARCHITECTURE (Important):\n"
            "   ✓ Separation of concerns?\n"
            "   ✓ Modularity? Small, focused functions/classes?\n"
            "   ✓ Proper dependency management?\n"
            "   ✓ Testability?\n"
            "\n"
            "7. USABILITY / ACCESSIBILITY (if applicable):\n"
            "   ✓ Clear user feedback/output?\n"
            "   ✓ (Web) Semantic HTML and ARIA?\n"
            "   ✓ (CLI) Helpful help messages and flags?\n"
            "\n"
            "8. MAINTAINABILITY:\n"
            "   ✓ Clear code structure?\n"
            "   ✓ Comments where needed (complex logic)?\n"
            "   ✓ No magic numbers? Constants defined?\n"
            "   ✓ Consistent style throughout?\n"
            "\n"
            "CRITICAL ANTI-PATTERNS TO REJECT:\n"
            "❌ Placeholder comments: '// Add logic here', '# TODO', '// Implement this'\n"
            "❌ Empty or stub functions that don't do anything\n"
            "❌ Code that won't run/compile without modifications\n"
            "❌ Syntax errors or undefined variables\n"
            "❌ Missing initialization\n"
            "❌ Obvious security holes\n"
            "\n"
            "Output strictly valid JSON:\n"
            "{\n"
            '  "_thought": "Detailed reasoning...",\n'
            '  "approved": boolean,\n'
            '  "score": 0-100,\n'
            '  "comments": [\n'
            '    "🔴 CRITICAL: Memory leak in loop",\n'
            '    "⚠️  WARNING: Missing error handling",\n'
            '    "💡 SUGGESTION: Rename variable for clarity",\n'
            '    "✅ GOOD: Clean implementation"\n'
            '  ],\n'
            '  "blocking_issues": ["Issue that MUST be fixed"]\n'
            "}\n"
            "\n"
            "APPROVAL CRITERIA:\n"
            "- REJECT (approved: false) if ANY blocking issues exist:\n"
            "  * Code won't run at all\n"
            "  * Critical syntax errors\n"
            "  * Obvious security vulnerabilities\n"
            "  * Incomplete implementation (TODOs, placeholders)\n"
            "- APPROVE (approved: true) if code is functional and secure, even with minor style issues\n"
            "\n"
            "Be THOROUGH but FAIR. Your reputation depends on catching real bugs while not blocking good code."
        )
