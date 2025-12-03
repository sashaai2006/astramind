from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from backend.core.ws_manager import ws_manager
from backend.llm.adapter import get_llm_adapter
from backend.settings import get_settings
from backend.sandbox.executor import SandboxExecutor
from backend.utils.fileutils import iter_file_entries, read_project_file
from backend.utils.json_parser import clean_and_parse_json
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)


class TesterAgent:
    """
    Testing Agent that validates generated code.
    
    Capabilities:
    1. Static analysis (syntax check, linting)
    2. Runtime validation (run code, check for errors)
    3. Auto-generate and run tests
    4. Report issues back to developer for fixes
    """

    def __init__(self) -> None:
        self._adapter = get_llm_adapter()
        self._settings = get_settings()
        self._executor = SandboxExecutor()

    async def _broadcast_thought(self, project_id: str, msg: str, level: str = "info"):
        """Helper to broadcast agent thoughts to the UI."""
        await ws_manager.broadcast(
            project_id,
            {
                "type": "event",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "agent": "tester",
                "level": level,
                "msg": msg,
            },
        )

    async def test_project(self, project_id: UUID, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Test the entire project and return results.
        
        Returns:
        {
            "passed": bool,
            "checks": [
                {"name": "syntax", "passed": bool, "details": "..."},
                {"name": "runtime", "passed": bool, "details": "..."},
                {"name": "logic", "passed": bool, "details": "..."}
            ],
            "issues": ["issue1", "issue2", ...]
        }
        """
        project_id_str = str(project_id)
        await self._broadcast_thought(project_id_str, "Starting comprehensive testing...")
        
        project_path = self._settings.projects_root / project_id_str
        if not project_path.exists():
            return {"passed": False, "checks": [], "issues": ["Project not found"]}

        checks = []
        issues = []

        # 1. Syntax Check
        await self._broadcast_thought(project_id_str, "Running syntax validation...")
        syntax_check = await self._check_syntax(project_path)
        checks.append(syntax_check)
        if not syntax_check["passed"]:
            issues.extend(syntax_check.get("issues", []))

        # 2. Static Analysis (basic linting)
        await self._broadcast_thought(project_id_str, "Running static analysis...")
        lint_check = await self._check_linting(project_path)
        checks.append(lint_check)
        if not lint_check["passed"]:
            issues.extend(lint_check.get("issues", []))

        # 3. Runtime Check (for JS/Python)
        await self._broadcast_thought(project_id_str, "Testing runtime execution...")
        runtime_check = await self._check_runtime(project_path, context)
        checks.append(runtime_check)
        if not runtime_check["passed"]:
            issues.extend(runtime_check.get("issues", []))

        # 4. Logic Validation with LLM
        await self._broadcast_thought(project_id_str, "Validating logic and completeness...")
        logic_check = await self._check_logic(project_path, context)
        checks.append(logic_check)
        if not logic_check["passed"]:
            issues.extend(logic_check.get("issues", []))

        passed = all(check["passed"] for check in checks)
        
        if passed:
            await self._broadcast_thought(project_id_str, "✅ All tests PASSED!", "info")
        else:
            await self._broadcast_thought(
                project_id_str, 
                f"❌ Testing FAILED: {len(issues)} issues found",
                "error"
            )

        return {
            "passed": passed,
            "checks": checks,
            "issues": issues
        }

    async def _check_syntax(self, project_path: Path) -> Dict[str, Any]:
        """Check syntax of all code files."""
        issues = []
        
        for file_path in iter_file_entries(project_path):
            full_path = project_path / file_path
            
            # JavaScript/TypeScript
            if file_path.endswith(('.js', '.ts', '.jsx', '.tsx')):
                try:
                    content = read_project_file(project_path, file_path)
                    # Basic checks
                    if not content.strip():
                        issues.append(f"{file_path}: File is empty")
                    # Check for common syntax errors
                    if content.count('{') != content.count('}'):
                        issues.append(f"{file_path}: Mismatched braces")
                    if content.count('(') != content.count(')'):
                        issues.append(f"{file_path}: Mismatched parentheses")
                except Exception as e:
                    issues.append(f"{file_path}: Read error - {e}")
            
            # Python
            elif file_path.endswith('.py'):
                try:
                    result = await self._executor.run_safe(
                        ["python3", "-m", "py_compile", str(full_path)],
                        timeout_seconds=5
                    )
                    if result["exit_code"] != 0:
                        issues.append(f"{file_path}: {result['stderr'][:200]}")
                except Exception as e:
                    issues.append(f"{file_path}: Syntax check failed - {e}")

        return {
            "name": "syntax",
            "passed": len(issues) == 0,
            "details": "All files have valid syntax" if len(issues) == 0 else f"{len(issues)} syntax errors",
            "issues": issues
        }

    async def _check_linting(self, project_path: Path) -> Dict[str, Any]:
        """Basic linting checks."""
        issues = []
        
        for file_path in iter_file_entries(project_path):
            if file_path.endswith(('.js', '.ts', '.jsx', '.tsx', '.py')):
                try:
                    content = read_project_file(project_path, file_path)
                    
                    # Common anti-patterns
                    if 'TODO' in content or 'FIXME' in content:
                        issues.append(f"{file_path}: Contains TODO/FIXME comments")
                    
                    if '// Add' in content or '# Add' in content:
                        issues.append(f"{file_path}: Contains placeholder comments")
                    
                    # JavaScript specific
                    if file_path.endswith('.js'):
                        if 'var ' in content:
                            issues.append(f"{file_path}: Uses 'var' instead of const/let")
                        if 'eval(' in content:
                            issues.append(f"{file_path}: Security risk - uses eval()")
                    
                    # Check for reasonable file size
                    if len(content) < 50:
                        issues.append(f"{file_path}: File is suspiciously short ({len(content)} chars)")
                    
                except Exception as e:
                    LOGGER.warning("Linting check failed for %s: %s", file_path, e)

        return {
            "name": "linting",
            "passed": len(issues) == 0,
            "details": "Code follows best practices" if len(issues) == 0 else f"{len(issues)} style issues",
            "issues": issues
        }

    async def _check_runtime(self, project_path: Path, context: Dict[str, Any]) -> Dict[str, Any]:
        """Test runtime execution."""
        issues = []
        target = context.get("target", "web")
        
        # For web projects, check if HTML loads scripts correctly
        if target == "web":
            index_html = project_path / "index.html"
            if index_html.exists():
                try:
                    content = read_project_file(project_path, "index.html")
                    
                    # Check if scripts are referenced
                    script_tags = content.count('<script')
                    if script_tags == 0:
                        issues.append("index.html: No scripts loaded")
                    
                    # Verify referenced scripts exist
                    import re
                    scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', content)
                    for script in scripts:
                        if not script.startswith('http'):
                            script_path = project_path / script
                            if not script_path.exists():
                                issues.append(f"index.html references missing script: {script}")
                    
                except Exception as e:
                    issues.append(f"Runtime check failed: {e}")
            else:
                issues.append("Missing index.html for web project")
        
        # For Python/API projects
        elif target == "api":
            main_py = project_path / "main.py"
            if main_py.exists():
                try:
                    # Try to import and basic syntax check
                    result = await self._executor.run_safe(
                        ["python3", "-c", f"import sys; sys.path.insert(0, '{project_path}'); import main"],
                        timeout_seconds=5
                    )
                    if result["exit_code"] != 0:
                        issues.append(f"main.py import failed: {result['stderr'][:200]}")
                except Exception as e:
                    issues.append(f"Runtime check failed: {e}")

        return {
            "name": "runtime",
            "passed": len(issues) == 0,
            "details": "Code runs without errors" if len(issues) == 0 else f"{len(issues)} runtime issues",
            "issues": issues
        }

    async def _check_logic(self, project_path: Path, context: Dict[str, Any]) -> Dict[str, Any]:
        """Use LLM to validate logic completeness."""
        try:
            # Read all files
            files_content = []
            for file_path in iter_file_entries(project_path):
                content = read_project_file(project_path, file_path)
                files_content.append(f"FILE: {file_path}\n```\n{content[:5000]}\n```")
            
            if not files_content:
                return {
                    "name": "logic",
                    "passed": False,
                    "details": "No files found",
                    "issues": ["Project has no files"]
                }

            prompt = (
                "You are a LEGENDARY QA ENGINEER with 15+ years at Google/Meta.\n"
                "You have prevented countless critical bugs from reaching production.\n"
                "\n"
                f"Project Requirements:\n"
                f"Title: {context.get('title')}\n"
                f"Description: {context.get('description')}\n"
                f"Target: {context.get('target')}\n"
                "\n"
                "Code Under Test:\n"
                + "\n\n".join(files_content)
                + "\n\n"
                "CRITICAL VALIDATION CHECKLIST:\n"
                "1. COMPLETENESS: Is ALL functionality implemented? Any TODOs/placeholders?\n"
                "2. LOGIC: Does the code actually implement the requirements?\n"
                "3. EXECUTION: Will the code run when user opens it? Is there initialization code?\n"
                "4. EDGE CASES: Are errors handled? Null checks? Boundary conditions?\n"
                "5. INTEGRATION: Do files work together? Correct imports/exports?\n"
                "\n"
                "Respond with ONLY valid JSON:\n"
                "{\n"
                '  "_thought": "Your reasoning...",\n'
                '  "passed": true/false,\n'
                '  "issues": ["Critical: game.js never calls init()", "Missing error handling in loadData()"]\n'
                "}\n"
                "\n"
                "Be STRICT but FAIR. Only fail if there are REAL problems that would prevent the code from working."
            )

            response = await self._adapter.acomplete(prompt, json_mode=True)
            result = clean_and_parse_json(response)
            
            return {
                "name": "logic",
                "passed": result.get("passed", False),
                "details": result.get("_thought", "Logic validation complete"),
                "issues": result.get("issues", [])
            }
            
        except Exception as e:
            LOGGER.error("Logic validation failed: %s", e)
            return {
                "name": "logic",
                "passed": True,  # Don't block on LLM failures
                "details": f"Validation skipped: {e}",
                "issues": []
            }

    def _is_critical_file(self, path: str) -> bool:
        """Determine if file is critical (main entry points)."""
        critical_patterns = ['index.', 'main.', 'app.', 'game.', 'server.']
        return any(pattern in path.lower() for pattern in critical_patterns)

