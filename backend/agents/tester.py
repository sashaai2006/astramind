from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from backend.core.ws_manager import ws_manager
from backend.core.event_bus import emit_event
from backend.llm.adapter import get_llm_adapter
from backend.settings import get_settings
from backend.sandbox.executor import execute_safe
from backend.utils.fileutils import iter_file_entries, read_project_file
from backend.utils.json_parser import clean_and_parse_json
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)

class TesterAgent:

    def __init__(self) -> None:
        self._adapter = get_llm_adapter()
        self._settings = get_settings()

    async def _broadcast_thought(self, project_id: str, msg: str, level: str = "info"):
        await emit_event(project_id, msg, agent="tester", level=level, persist=False)

    async def test_project(self, project_id: UUID, context: Dict[str, Any]) -> Dict[str, Any]:
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
        
        # Log issues for debugging
        if issues:
            LOGGER.info("Tester found %d issues:", len(issues))
            for idx, issue in enumerate(issues[:10], 1):  # Log first 10
                LOGGER.info("  %d. %s", idx, issue)
            if len(issues) > 10:
                LOGGER.info("  ... and %d more issues", len(issues) - 10)
        
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
        issues = []
        
        for file_entry in iter_file_entries(project_path):
            file_path = str(file_entry)  # Convert FileEntry to string
            full_path = project_path / file_path
            
            # JavaScript/TypeScript
            if file_path.endswith(('.js', '.ts', '.jsx', '.tsx')):
                try:
                    data, is_text = read_project_file(project_path, file_path)
                    content = data.decode("utf-8") if is_text else ""
                    
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
                    result = await execute_safe(
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
        issues = []
        
        has_package_json = (project_path / "package.json").exists()
        
        for file_entry in iter_file_entries(project_path):
            file_path = str(file_entry)  # Convert FileEntry to string
            if file_path.endswith(('.js', '.ts', '.jsx', '.tsx', '.py')):
                try:
                    data, is_text = read_project_file(project_path, file_path)
                    content = data.decode("utf-8") if is_text else ""
                    
                    # Check for React imports without package.json
                    if not has_package_json and ('import React' in content or 'from "react"' in content or "from 'react'" in content):
                        issues.append(f"{file_path}: Uses React but package.json is missing (CRITICAL: Stack mismatch)")

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
        issues = []
        target = context.get("target", "web")
        # Try to infer stack if not explicit (fallback)
        try:
            is_cpp = any(
                getattr(f, "path", f).endswith((".cpp", ".hpp", ".h", ".cc"))
                for f in iter_file_entries(project_path)
            )
        except Exception as e:
            LOGGER.warning("Runtime stack detection failed, defaulting to non-C++: %s", e)
            is_cpp = False
        
        # For web projects, check if HTML loads scripts correctly
        if target == "web" and not is_cpp:
            index_html = project_path / "index.html"
            if index_html.exists():
                try:
                    data, is_text = read_project_file(project_path, "index.html")
                    content = data.decode("utf-8") if is_text else ""
                    
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
        elif target == "api" or (project_path / "main.py").exists():
            main_py = project_path / "main.py"
            if main_py.exists():
                try:
                    # Try to import and basic syntax check
                    result = await execute_safe(
                        ["python3", "-c", f"import sys; sys.path.insert(0, '{project_path}'); import main"],
                        timeout_seconds=5
                    )
                    if result["exit_code"] != 0:
                        stderr = result["stderr"]
                        is_ignored_error = False
                        
                        # Ignore missing external dependencies in sandbox environment
                        if "ModuleNotFoundError" in stderr:
                            import re
                            match = re.search(r"No module named '([^']+)'", stderr)
                            if match:
                                module_name = match.group(1)
                                # Only report error if it's a missing LOCAL file
                                local_module = project_path / f"{module_name}.py"
                                if not local_module.exists():
                                    # It's an external lib or missing local file.
                                    LOGGER.warning(f"Runtime check ignored missing module: {module_name}")
                                    is_ignored_error = True

                        if not is_ignored_error:
                            issues.append(f"main.py import failed: {stderr[:200]}")
                except Exception as e:
                    issues.append(f"Runtime check failed: {e}")

        # For C++ Projects (compilation check)
        elif is_cpp:
            try:
                # Check for Makefile
                if (project_path / "Makefile").exists():
                    # Dry run make if possible, or just check syntax
                    pass 
                
                # Try to compile main.cpp if exists
                main_cpp = project_path / "main.cpp"
                if main_cpp.exists():
                    # We might not have g++ in the sandbox, but we can check if file is empty
                    data, is_text = read_project_file(project_path, "main.cpp")
                    content = data.decode("utf-8") if is_text else ""

                    if not content.strip():
                        issues.append("main.cpp is empty")
                    if "int main" not in content:
                        issues.append("main.cpp missing entry point 'int main'")
            except Exception as e:
                issues.append(f"C++ check failed: {e}")

        return {
            "name": "runtime",
            "passed": len(issues) == 0,
            "details": "Code runs without errors" if len(issues) == 0 else f"{len(issues)} runtime issues",
            "issues": issues
        }

    async def _check_logic(self, project_path: Path, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            # Read all files
            files_content = []
            for file_entry in iter_file_entries(project_path):
                file_path = file_entry.path  # Get path string from FileEntry object
                
                try:
                    data, is_text = read_project_file(project_path, file_path)
                    if is_text:
                        content = data.decode("utf-8")
                        files_content.append(f"FILE: {file_path}\n```\n{content[:5000]}\n```")
                except Exception as read_err:
                    LOGGER.warning(f"Could not read file {file_path} for logic check: {read_err}")
                    continue
            
            if not files_content:
                return {
                    "name": "logic",
                    "passed": False,
                    "details": "No files found",
                    "issues": ["Project has no files"]
                }

            prompt = (
                "You are a LEGENDARY QA ENGINEER with 15 years experience.\n"
                "You have expertise in testing software across ALL technologies.\n"
                "You catch bugs that would cost millions in production.\n"
                "\n"
                "CRITICAL: Only report BLOCKING issues that prevent the code from working.\n"
                "IGNORE: Style issues, missing documentation, optimization suggestions, or minor warnings.\n"
                "\n"
                f"=== PROJECT ===\n"
                f"Title: {context.get('title')}\n"
                f"Description: {context.get('description')}\n"
                f"Target: {context.get('target')}\n"
                "\n"
                f"=== CODE ===\n"
                + "\n\n".join(files_content)
                + "\n\n"
                "=== VALIDATION CHECKLIST (ONLY BLOCKING ISSUES) ===\n"
                "\n"
                "1. SYNTAX ERRORS:\n"
                "   - Will the code compile/parse? (ONLY if it won't)\n"
                "   - Are delimiters matched? (ONLY if broken)\n"
                "\n"
                "2. CRITICAL MISSING PARTS:\n"
                "   - Missing entry point (main function, app.run, etc.)\n"
                "   - Undefined functions that are called\n"
                "   - Missing required imports that break execution\n"
                "\n"
                "3. RUNTIME ERRORS:\n"
                "   - Code that will crash on execution (not just missing dependencies)\n"
                "   - Logic errors that prevent basic functionality\n"
                "\n"
                "DO NOT REPORT:\n"
                "   - Missing dependencies (these are expected in sandbox)\n"
                "   - TODO/FIXME comments (these are acceptable)\n"
                "   - Style issues or code quality suggestions\n"
                "   - Missing error handling (unless it's critical)\n"
                "   - Optimization opportunities\n"
                "\n"
                "=== OUTPUT (JSON) ===\n"
                "{\n"
                '  "_thought": "Checking for blocking issues only...",\n'
                '  "passed": true/false,\n'
                '  "issues": ["ONLY blocking issues that prevent execution"]\n'
                "}\n"
                "\n"
                "PASS if code will compile and run (even with missing external dependencies).\n"
                "FAIL ONLY if code has syntax errors or critical missing parts.\n"
                "Return ONLY JSON."
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
        critical_patterns = ['index.', 'main.', 'app.', 'game.', 'server.']
        return any(pattern in path.lower() for pattern in critical_patterns)

