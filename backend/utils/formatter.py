from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)


class CodeFormatter:
    """
    Auto-formatter for generated code.
    Fixes common issues and beautifies code without external dependencies.
    """

    @staticmethod
    async def format_project(project_path: Path) -> Dict[str, int]:
        """
        Format all files in a project.
        
        Returns:
            Dict with counts: {"formatted": N, "skipped": M, "errors": K}
        """
        results = {"formatted": 0, "skipped": 0, "errors": 0}
        
        for file_path in project_path.rglob("*"):
            if not file_path.is_file():
                continue
            
            ext = file_path.suffix.lower()
            
            try:
                if ext in ['.js', '.jsx', '.ts', '.tsx']:
                    changed = await CodeFormatter._format_javascript(file_path)
                    results["formatted" if changed else "skipped"] += 1
                
                elif ext == '.py':
                    changed = await CodeFormatter._format_python(file_path)
                    results["formatted" if changed else "skipped"] += 1
                
                elif ext in ['.html', '.htm']:
                    changed = await CodeFormatter._format_html(file_path)
                    results["formatted" if changed else "skipped"] += 1
                
                elif ext == '.css':
                    changed = await CodeFormatter._format_css(file_path)
                    results["formatted" if changed else "skipped"] += 1
                
                elif ext == '.json':
                    changed = await CodeFormatter._format_json(file_path)
                    results["formatted" if changed else "skipped"] += 1
                
            except Exception as e:
                LOGGER.warning("Failed to format %s: %s", file_path, e)
                results["errors"] += 1
        
        return results

    @staticmethod
    async def _format_javascript(file_path: Path) -> bool:
        """Format JavaScript/TypeScript file."""
        content = file_path.read_text(encoding='utf-8')
        original = content
        
        # Fix common issues
        content = CodeFormatter._fix_indentation(content, 2)
        content = CodeFormatter._fix_semicolons(content)
        content = CodeFormatter._fix_spacing(content)
        content = CodeFormatter._remove_trailing_whitespace(content)
        content = CodeFormatter._ensure_final_newline(content)
        
        if content != original:
            file_path.write_text(content, encoding='utf-8')
            return True
        return False

    @staticmethod
    async def _format_python(file_path: Path) -> bool:
        """Format Python file (basic PEP 8)."""
        content = file_path.read_text(encoding='utf-8')
        original = content
        
        # Fix common issues
        content = CodeFormatter._fix_indentation(content, 4)
        content = CodeFormatter._fix_spacing(content)
        content = CodeFormatter._remove_trailing_whitespace(content)
        content = CodeFormatter._ensure_final_newline(content)
        
        # Python-specific fixes
        # Add blank lines around class/function definitions
        lines = content.split('\n')
        formatted_lines = []
        prev_was_def = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            is_def = stripped.startswith('def ') or stripped.startswith('class ')
            
            # Add blank line before def/class (except at start)
            if is_def and i > 0 and formatted_lines and formatted_lines[-1].strip():
                if not prev_was_def:
                    formatted_lines.append('')
            
            formatted_lines.append(line)
            prev_was_def = is_def
        
        content = '\n'.join(formatted_lines)
        
        if content != original:
            file_path.write_text(content, encoding='utf-8')
            return True
        return False

    @staticmethod
    async def _format_html(file_path: Path) -> bool:
        """Format HTML file."""
        content = file_path.read_text(encoding='utf-8')
        original = content
        
        # Basic HTML formatting
        content = CodeFormatter._remove_trailing_whitespace(content)
        content = CodeFormatter._ensure_final_newline(content)
        
        if content != original:
            file_path.write_text(content, encoding='utf-8')
            return True
        return False

    @staticmethod
    async def _format_css(file_path: Path) -> bool:
        """Format CSS file."""
        content = file_path.read_text(encoding='utf-8')
        original = content
        
        # Basic CSS formatting
        content = CodeFormatter._fix_indentation(content, 2)
        content = CodeFormatter._remove_trailing_whitespace(content)
        content = CodeFormatter._ensure_final_newline(content)
        
        if content != original:
            file_path.write_text(content, encoding='utf-8')
            return True
        return False

    @staticmethod
    async def _format_json(file_path: Path) -> bool:
        """Format JSON file."""
        try:
            content = file_path.read_text(encoding='utf-8')
            data = json.loads(content)
            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            formatted = CodeFormatter._ensure_final_newline(formatted)
            
            if formatted != content:
                file_path.write_text(formatted, encoding='utf-8')
                return True
        except json.JSONDecodeError:
            LOGGER.warning("Invalid JSON in %s", file_path)
        return False

    @staticmethod
    def _fix_indentation(content: str, indent_size: int) -> str:
        """Fix inconsistent indentation."""
        lines = content.split('\n')
        fixed_lines = []
        
        for line in lines:
            if not line.strip():
                fixed_lines.append('')
                continue
            
            # Count leading spaces/tabs
            leading = len(line) - len(line.lstrip())
            if '\t' in line[:leading]:
                # Replace tabs with spaces
                tabs = line[:leading].count('\t')
                spaces = line[:leading].count(' ')
                total_indent = tabs * indent_size + spaces
                line = ' ' * total_indent + line.lstrip()
            
            fixed_lines.append(line)
        
        return '\n'.join(fixed_lines)

    @staticmethod
    def _fix_semicolons(content: str) -> str:
        """Add missing semicolons in JavaScript."""
        lines = content.split('\n')
        fixed_lines = []
        
        for line in lines:
            stripped = line.rstrip()
            if not stripped or stripped.endswith(('{', '}', ';', ',', ':', '//')):
                fixed_lines.append(line)
                continue
            
            # Check if line should have semicolon
            if any(stripped.startswith(kw) for kw in ['const ', 'let ', 'var ', 'return ', 'throw ', 'break', 'continue']):
                if not stripped.endswith(';'):
                    line = stripped + ';'
            
            fixed_lines.append(line)
        
        return '\n'.join(fixed_lines)

    @staticmethod
    def _fix_spacing(content: str) -> str:
        """Fix spacing around operators."""
        # Add spaces around operators (basic)
        content = re.sub(r'(\w)([+\-*/%=<>!&|])(\w)', r'\1 \2 \3', content)
        
        # Remove multiple spaces
        content = re.sub(r'  +', ' ', content)
        
        # Fix spacing after commas
        content = re.sub(r',(\S)', r', \1', content)
        
        return content

    @staticmethod
    def _remove_trailing_whitespace(content: str) -> str:
        """Remove trailing whitespace from all lines."""
        lines = content.split('\n')
        return '\n'.join(line.rstrip() for line in lines)

    @staticmethod
    def _ensure_final_newline(content: str) -> str:
        """Ensure file ends with a newline."""
        if content and not content.endswith('\n'):
            return content + '\n'
        return content

    @staticmethod
    def _remove_multiple_blank_lines(content: str) -> str:
        """Remove consecutive blank lines (max 2)."""
        return re.sub(r'\n{4,}', '\n\n\n', content)

