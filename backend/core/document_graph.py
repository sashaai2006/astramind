from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph

from backend.core.document_state import DocumentState
from backend.core.document_event_bus import emit_document_event
from backend.llm.adapter import get_llm_adapter
from backend.memory.db import get_session
from backend.memory import utils as db_utils
from backend.sandbox.executor import execute_safe
from backend.settings import get_settings
from backend.utils.fileutils import write_files_async
from backend.utils.json_parser import clean_and_parse_json
from backend.utils.logging import get_logger

LOGGER = get_logger(__name__)

# Beamer themes available in tectonic
BEAMER_THEMES = ["Madrid", "Berlin", "Copenhagen", "Singapore", "Warsaw", "AnnArbor", "CambridgeUS"]
BEAMER_COLOR_THEMES = ["default", "beaver", "crane", "dolphin", "dove", "lily", "orchid", "rose", "seagull", "seahorse", "whale", "wolverine"]

# Russian preamble for Cyrillic support (tectonic-friendly)
# IMPORTANT: tectonic doesn't ship full T2A font metrics by default, so we avoid \usepackage[T2A]{fontenc}.
# The combination below compiles with tectonic and supports UTF-8 Cyrillic text.
RUSSIAN_PREAMBLE = r"""\usepackage[utf8]{inputenc}
\usepackage[russian]{babel}
"""


def _has_cyrillic(text: str) -> bool:
    """Check if text contains Cyrillic characters."""
    return any('\u0400' <= c <= '\u04FF' for c in text)


def _fix_broken_cyrillic(content: str) -> str:
    """Fix common broken Cyrillic patterns from LLM output."""
    import re
    
    # Fix patterns like \Введение -> Введение (remove backslash before Cyrillic)
    content = re.sub(r'\\([А-Яа-яЁё])', r'\1', content)
    
    # Fix patterns like \producedводная -> производная (LLM confusion)
    # This is harder to fix automatically, but we can try common patterns
    broken_patterns = {
        r'\\produced': 'произ',
        r'\\Produced': 'Произ',
    }
    for pattern, replacement in broken_patterns.items():
        content = content.replace(pattern, replacement)
    
    return content


def _validate_latex_brackets(content: str) -> tuple[bool, list[str]]:  # type: ignore[misc]
    """Validate LaTeX bracket matching and return errors."""
    import re
    errors = []
    
    # Check curly braces {} matching
    open_braces = content.count('{')
    close_braces = content.count('}')
    if open_braces != close_braces:
        errors.append(f"Mismatched curly braces: {open_braces} open, {close_braces} close")
    
    # Check for common bracket errors in commands like \title{text) instead of \title{text}
    # Pattern: \command{text) - closing with ) instead of }
    bracket_errors = re.findall(r'\\(title|author|date|section|subsection|subsubsection)\{[^}]*\)', content)
    if bracket_errors:
        errors.append(f"Found commands with wrong closing bracket (using ) instead of }}): {', '.join(set(bracket_errors))}")
    
    # Check for unmatched brackets in specific contexts
    lines = content.split('\n')
    for i, line in enumerate(lines, 1):
        # Check for \title{...), \author{...), etc.
        if re.search(r'\\(title|author|date|section|subsection)\{[^}]*\)', line):
            errors.append(f"Line {i}: Wrong closing bracket - use }} instead of )")
    
    return len(errors) == 0, errors


def _fix_latex_bracket_errors(content: str) -> str:
    """Automatically fix common LaTeX bracket errors."""
    import re
    
    # Fix \command{text) -> \command{text}
    # But be careful - only fix if it's clearly wrong (not inside math mode)
    def fix_line(line: str) -> str:
        # Fix patterns like \title{text) -> \title{text}
        # Only if there's no matching } before the )
        patterns = [
            (r'\\(title|author|date)\{([^}]+)\)', r'\\\1{\2}'),
            (r'\\(section|subsection|subsubsection)\{([^}]+)\)', r'\\\1{\2}'),
        ]
        for pattern, replacement in patterns:
            line = re.sub(pattern, replacement, line)
        return line
    
    lines = content.split('\n')
    fixed_lines = [fix_line(line) for line in lines]
    return '\n'.join(fixed_lines)


def _fix_russian_preamble(content: str) -> str:
    """Ensure Russian document has proper preamble for Cyrillic (tectonic-friendly)."""
    # First fix broken Cyrillic
    content = _fix_broken_cyrillic(content)
    
    if not _has_cyrillic(content):
        return content
    
    # Check if already has Russian support
    has_russian_support = (
        "russian" in content.lower() or 
        "babel" in content.lower()
    )
    
    if has_russian_support:
        # If legacy T2A/fontenc is present, remove it to avoid missing font metrics in tectonic.
        if "T2A" in content or "fontenc" in content.lower() or "fontspec" in content.lower():
            import re
            # Drop fontenc/fontspec blocks if present
            content = re.sub(r"\\usepackage\[[^\]]*\]\{fontenc\}\s*", "", content)
            content = re.sub(r"\\usepackage\{fontspec\}\s*", "", content)
            # Drop any engine directives; tectonic doesn't run xelatex.
            content = re.sub(r"^%\\s*!TEX\\s+program\\s*=\\s*xelatex\\s*\\n", "", content, flags=re.IGNORECASE | re.MULTILINE)
            # Ensure inputenc+babel are present
            if "inputenc" not in content.lower():
                content = re.sub(
                    r"(\\documentclass\{[^\}]+\}\s*)",
                    r"\1" + RUSSIAN_PREAMBLE.strip() + "\n",
                    content,
                    count=1,
                )
            if "babel" not in content.lower():
                content = re.sub(
                    r"(\\documentclass\{[^\}]+\}\s*)",
                    r"\1\\usepackage[russian]{babel}\n",
                    content,
                    count=1,
                )
        return content
    
    # Insert preamble after \documentclass line
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.strip().startswith(r'\documentclass'):
            lines.insert(i + 1, RUSSIAN_PREAMBLE)
            break
    
    return '\n'.join(lines)


def _doc_root(document_id: str) -> Path:
    settings = get_settings()
    root = (settings.documents_root / document_id).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _latex_system_prompt(preset: Optional[str], persona_prompt: Optional[str] = None) -> str:
    persona = preset or "LaTeX Writer"
    persona_block = ""
    if persona_prompt and persona_prompt.strip():
        persona_block = persona_prompt.strip() + "\n\n"
    return (
        persona_block + f"You are a specialized agent: {persona}.\n"
        "You write high-quality LaTeX.\n"
        "Rules:\n"
        "- Produce compilable LaTeX with tectonic.\n"
        "- Prefer a single main.tex for MVP.\n"
        "- Avoid external images unless requested.\n"
        "- Avoid unsupported packages when possible.\n"
        "- For non-English text (Russian, German, etc.), ALWAYS use UTF-8 encoding.\n"
        "- For Russian/Cyrillic with tectonic, use ONLY:\n"
        "  \\usepackage[utf8]{inputenc}\n"
        "  \\usepackage[russian]{babel}\n"
        "- Write Russian text directly in UTF-8 (e.g. 'Привет мир'), NOT with escape codes.\n"
        "- Do NOT use \\usepackage[T2A]{fontenc} (tectonic often misses required TFM fonts).\n"
    )


async def plan_node(state: DocumentState) -> Dict[str, Any]:
    document_id = state["document_id"]
    await emit_document_event(document_id, "Planning document outline...", agent="latex_writer")

    adapter = get_llm_adapter()
    doc_type = state.get("doc_type") or "latex_article"
    preset = state.get("agent_preset")

    settings = get_settings()
    if settings.llm_mode == "mock":
        return {"outline": "1) Introduction\n2) Main content\n3) Conclusion", "status": "writing"}

    prompt = (
        _latex_system_prompt(preset, state.get("persona_prompt"))
        + "\n"
        + "TASK: Create a concise outline for the document.\n"
        + f"Title: {state['title']}\n"
        + f"Description: {state['description']}\n"
        + f"Doc type: {doc_type}\n"
        + "\n"
        + "Return ONLY JSON:\n"
        + "{\n"
        + '  "outline": "string outline with sections"\n'
        + "}\n"
    )

    raw = await adapter.acomplete(prompt, json_mode=True)
    data = clean_and_parse_json(raw)
    outline = data.get("outline", "") if isinstance(data, dict) else ""
    if not outline:
        raise ValueError("Failed to generate outline")

    return {
        "outline": outline,
        "status": "writing",
    }


async def write_node(state: DocumentState) -> Dict[str, Any]:
    document_id = state["document_id"]
    await emit_document_event(document_id, "Writing LaTeX files...", agent="latex_writer")

    adapter = get_llm_adapter()
    doc_type = state.get("doc_type") or "latex_article"
    preset = state.get("agent_preset")
    outline = state.get("outline", "")

    settings = get_settings()
    if settings.llm_mode == "mock":
        root = _doc_root(document_id)
        main = (
            "\\documentclass{article}\n"
            "\\title{Mock Document}\n"
            "\\author{AstraMind}\n"
            "\\begin{document}\n"
            "\\maketitle\n"
            "Hello from mock LaTeX.\n"
            "\\end{document}\n"
        )
        await write_files_async(root, [{"path": "main.tex", "content": main}])
        return {"main_tex_path": "main.tex", "status": "reviewing"}

    template_hint = "article" if doc_type == "latex_article" else "beamer"

    # Detect if Russian/Cyrillic content is needed
    needs_russian = _has_cyrillic(state.get("title", "") + state.get("description", "") + outline)
    
    lang_hint = ""
    if needs_russian:
        lang_hint = (
            "\n=== CRITICAL: RUSSIAN LANGUAGE DOCUMENT ===\n"
            "This document is in RUSSIAN. Follow these rules EXACTLY:\n"
            "\n"
            "1. Include these packages RIGHT AFTER \\documentclass{...}:\n"
            "   \\usepackage[utf8]{inputenc}\n"
            "   \\usepackage[russian]{babel}\n"
            "\n"
            "2. Write ALL Russian text as plain UTF-8 characters:\n"
            "   CORRECT: \\section{Введение}\n"
            "   CORRECT: \\title{Производная функции}\n"
            "   WRONG: \\section{\\Введение}  (no backslash before Russian!)\n"
            "   WRONG: \\title{\\cyr...}  (no escape codes!)\n"
            "   WRONG: \\title{\\u043f...}  (no unicode escapes!)\n"
            "\n"
            "3. Example of correct Russian LaTeX (tectonic-friendly):\n"
            "   \\documentclass{article}\n"
            "   \\usepackage[utf8]{inputenc}\n"
            "   \\usepackage[russian]{babel}\n"
            "   \\title{Математический анализ}\n"
            "   \\begin{document}\n"
            "   \\maketitle\n"
            "   \\section{Введение}\n"
            "   Текст на русском языке.\n"
            "   \\end{document}\n"
            "\n"
            "4. CRITICAL: Always wrap text content in paragraphs:\n"
            "   CORRECT: \\section{Введение}\\n   Текст параграфа.\\n   Еще текст.\\n"
            "   WRONG: \\section{Введение}\\nТекст без параграфа\\n"
            "   Text after \\section{} should be regular paragraph text, not bare.\n"
            "\n"
        )
    
    prompt = (
        _latex_system_prompt(preset, state.get("persona_prompt"))
        + "\n"
        + "TASK: Write a complete LaTeX document.\n"
        + f"Document class: {template_hint}\n"
        + f"Title: {state['title']}\n"
        + f"Outline:\n{outline}\n"
        + lang_hint
        + "\n"
        + "IMPORTANT STRUCTURE RULES:\n"
        + "- After \\section{}, \\subsection{}, etc., write paragraph text directly (no \\paragraph{} needed).\n"
        + "- Each paragraph should be separated by blank lines.\n"
        + "- Ensure all curly braces {} are properly matched.\n"
        + "- Use } not ) to close command arguments like \\title{}, \\section{}, etc.\n"
        + "\n"
        + "Return ONLY JSON:\n"
        + "{\n"
        + '  "files": [\n'
        + '    {"path":"main.tex","content":"...full latex..."}\n'
        + "  ]\n"
        + "}\n"
    )

    raw = await adapter.acomplete(prompt, json_mode=True)
    data = clean_and_parse_json(raw)
    files = []
    if isinstance(data, dict):
        files = data.get("files", [])
    if not isinstance(files, list) or not files:
        raise ValueError("LLM returned no files")

    # Fix Russian preamble and validate/fix LaTeX syntax
    for f in files:
        if f.get("path", "").endswith(".tex") and isinstance(f.get("content"), str):
            content = f["content"]
            # Fix Russian preamble
            content = _fix_russian_preamble(content)
            # Fix bracket errors automatically
            content = _fix_latex_bracket_errors(content)
            # Validate and log errors
            is_valid, errors = _validate_latex_brackets(content)
            if not is_valid:
                await emit_document_event(
                    document_id,
                    f"LaTeX validation warnings: {'; '.join(errors)}",
                    agent="latex_writer",
                    level="warning"
                )
            f["content"] = content

    # Write to documents root
    root = _doc_root(document_id)
    saved = await write_files_async(root, files)

    # Record artifacts (best effort)
    try:
        rel_paths = [p.relative_to(root).as_posix() for p in saved]
        sizes = [p.stat().st_size for p in saved]
        async with get_session() as session:
            await db_utils.add_document_artifacts(session, UUID(document_id), rel_paths, sizes)
    except Exception:
        LOGGER.exception("Failed to record document artifacts")

    return {
        "main_tex_path": "main.tex",
        "status": "reviewing",
    }


async def review_node(state: DocumentState) -> Dict[str, Any]:
    document_id = state["document_id"]
    await emit_document_event(document_id, "Reviewing LaTeX for compilation issues...", agent="reviewer")

    root = _doc_root(document_id)
    main_path = root / "main.tex"
    content = main_path.read_text(encoding="utf-8") if main_path.exists() else ""
    if not content:
        raise ValueError("main.tex missing")

    # First, validate and auto-fix basic errors
    content = _fix_latex_bracket_errors(content)
    is_valid, errors = _validate_latex_brackets(content)
    
    if not is_valid:
        await emit_document_event(
            document_id,
            f"Found LaTeX syntax errors: {'; '.join(errors)}. Attempting to fix...",
            agent="reviewer",
            level="warning"
        )
        # Try to fix automatically
        content = _fix_latex_bracket_errors(content)
        # Re-validate
        is_valid, errors = _validate_latex_brackets(content)
        if is_valid:
            await emit_document_event(
                document_id,
                "Auto-fixed bracket errors.",
                agent="reviewer",
                level="info"
            )
        else:
            await emit_document_event(
                document_id,
                f"Still have errors after auto-fix: {'; '.join(errors)}. Asking LLM to fix...",
                agent="reviewer",
                level="warning"
            )

    adapter = get_llm_adapter()
    validation_hint = ""
    if not is_valid:
        validation_hint = f"\nCRITICAL ERRORS FOUND:\n" + "\n".join(f"- {e}" for e in errors) + "\n"
    
    # If Russian, enforce tectonic-friendly preamble (no T2A/fontspec)
    needs_russian = _has_cyrillic(content)
    russian_hint = ""
    if needs_russian:
        russian_hint = (
            "\nIMPORTANT: Russian text detected.\n"
            "- Ensure preamble includes ONLY: \\usepackage[utf8]{inputenc} and \\usepackage[russian]{babel}\n"
            "- Remove \\usepackage[T2A]{fontenc} and \\usepackage{fontspec} if present.\n"
            "\n"
        )
    
    prompt = (
        "You are a LaTeX reviewer and compiler expert.\n"
        "Task: Fix ALL issues that would prevent compilation with tectonic.\n"
        "\n"
        "Common errors to fix:\n"
        "- Mismatched curly braces {} - ensure every { has a matching }\n"
        "- Wrong closing brackets: \\title{text) should be \\title{text}\n"
        "- Missing or extra braces in commands\n"
        "- Text after sections should be regular paragraph text (no special formatting needed)\n"
        + russian_hint
        + "\n"
        + validation_hint
        + "\n"
        "Return ONLY JSON: {\"content\": \"full fixed main.tex\"}\n"
        "\n"
        "Current main.tex:\n"
        + content[:20000]
    )
    raw = await adapter.acomplete(prompt, json_mode=True)
    data = clean_and_parse_json(raw)
    new_content = data.get("content", "") if isinstance(data, dict) else ""
    if new_content and isinstance(new_content, str):
        # Final validation after LLM fix
        new_content = _fix_latex_bracket_errors(new_content)
        final_valid, final_errors = _validate_latex_brackets(new_content)
        if final_valid:
            await emit_document_event(
                document_id,
                "LaTeX review completed. All syntax errors fixed.",
                agent="reviewer",
                level="info"
            )
        else:
            await emit_document_event(
                document_id,
                f"Review completed but some errors remain: {'; '.join(final_errors)}",
                agent="reviewer",
                level="warning"
            )
        await write_files_async(root, [{"path": "main.tex", "content": new_content}])
    else:
        await emit_document_event(
            document_id,
            "Reviewer made no changes. Proceeding with original content.",
            agent="reviewer",
            level="warning"
        )
    return {"status": "compiling"}


async def designer_node(state: DocumentState) -> Dict[str, Any]:
    """Apply visual theme/colors for beamer presentations."""
    document_id = state["document_id"]
    await emit_document_event(document_id, "Applying presentation design (theme & colors)...", agent="designer")

    root = _doc_root(document_id)
    main_path = root / "main.tex"
    content = main_path.read_text(encoding="utf-8") if main_path.exists() else ""
    if not content:
        raise ValueError("main.tex missing for design step")

    settings = get_settings()
    adapter = get_llm_adapter()

    if settings.llm_mode == "mock":
        # In mock mode, just add a default theme if not present
        if "\\usetheme" not in content:
            # Insert after \documentclass{beamer}
            content = content.replace(
                "\\documentclass{beamer}",
                "\\documentclass{beamer}\n\\usetheme{Madrid}\n\\usecolortheme{default}"
            )
            await write_files_async(root, [{"path": "main.tex", "content": content}])
        await emit_document_event(document_id, "Design applied (mock).", agent="designer")
        return {"status": "compiling"}

    prompt = (
        "You are a Beamer presentation designer.\n"
        f"Available themes: {', '.join(BEAMER_THEMES)}\n"
        f"Available color themes: {', '.join(BEAMER_COLOR_THEMES)}\n"
        "\n"
        "Task: Enhance this beamer presentation with:\n"
        "1. A professional theme (\\usetheme{...})\n"
        "2. A matching color theme (\\usecolortheme{...})\n"
        "3. Nice title slide formatting if missing\n"
        "4. Frame titles and section structure improvements\n"
        "\n"
        "Return ONLY JSON: {\"content\": \"full improved main.tex\"}\n"
        "\n"
        "Current main.tex:\n"
        + content[:20000]
    )

    raw = await adapter.acomplete(prompt, json_mode=True)
    data = clean_and_parse_json(raw)
    new_content = data.get("content", "") if isinstance(data, dict) else ""
    if new_content and isinstance(new_content, str):
        await write_files_async(root, [{"path": "main.tex", "content": new_content}])
        await emit_document_event(document_id, "Design enhancements applied.", agent="designer")
    else:
        await emit_document_event(document_id, "Designer made no changes.", agent="designer", level="warning")

    return {"status": "compiling"}


async def compile_node(state: DocumentState) -> Dict[str, Any]:
    document_id = state["document_id"]
    await emit_document_event(document_id, "Compiling to PDF (tectonic)...", agent="compiler")

    settings = get_settings()
    root = _doc_root(document_id)

    if settings.llm_mode == "mock":
        # Minimal valid PDF (enough for download tests / UI wiring)
        pdf = root / "main.pdf"
        pdf.write_bytes(
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
            b"xref\n0 3\n0000000000 65535 f \n0000000010 00000 n \n0000000062 00000 n \n"
            b"trailer<</Size 3/Root 1 0 R>>\nstartxref\n116\n%%EOF\n"
        )
        await emit_document_event(document_id, "PDF compiled successfully (mock).", agent="compiler")
        return {"pdf_path": "main.pdf", "status": "done"}

    if shutil.which("tectonic") is None:
        error_msg = "tectonic is not installed on server PATH"
        await emit_document_event(
            document_id,
            f"Compilation failed: {error_msg}",
            agent="compiler",
            level="error"
        )
        raise RuntimeError(error_msg)

    # Validate LaTeX before compilation
    main_path = root / "main.tex"
    use_xelatex = False
    if main_path.exists():
        content = main_path.read_text(encoding="utf-8")
        is_valid, errors = _validate_latex_brackets(content)
        if not is_valid:
            await emit_document_event(
                document_id,
                f"LaTeX syntax errors detected before compilation: {'; '.join(errors)}",
                agent="compiler",
                level="warning"
            )
        # Check if document needs XeLaTeX (Russian/Cyrillic or explicit directive)
        # Keep flag for logging only; tectonic 0.15 doesn't run xelatex.
        use_xelatex = "fontspec" in content.lower()

    if use_xelatex:
        await emit_document_event(
            document_id,
            "Note: fontspec detected, but tectonic does not run xelatex; removing fontspec is recommended.",
            agent="compiler",
            level="warning",
        )
    
    result = await execute_safe(["tectonic", "main.tex"], timeout_seconds=60, cwd=root)
    if result.get("exit_code") != 0:
        stderr = str(result.get("stderr", ""))[:2000]
        stdout = str(result.get("stdout", ""))[:1000]
        
        # Extract error message (tectonic usually puts errors in stderr)
        error_details = stderr if stderr else stdout
        if not error_details:
            error_details = "Unknown compilation error"
        
        # Log error to UI
        await emit_document_event(
            document_id,
            f"Compilation failed: {error_details}",
            agent="compiler",
            level="error",
            data={"stderr": stderr[:500], "stdout": stdout[:500]}
        )
        
        # Also update state with error
        return {
            "status": "failed",
            "error": error_details[:500]
        }

    pdf = root / "main.pdf"
    if not pdf.exists():
        error_msg = "PDF was not produced by tectonic"
        await emit_document_event(
            document_id,
            f"Compilation failed: {error_msg}",
            agent="compiler",
            level="error"
        )
        raise RuntimeError(error_msg)

    # Record artifact
    try:
        async with get_session() as session:
            await db_utils.add_document_artifacts(
                session, UUID(document_id), ["main.pdf"], [pdf.stat().st_size]
            )
    except Exception:
        LOGGER.exception("Failed to record PDF artifact")

    await emit_document_event(document_id, "PDF compiled successfully.", agent="compiler")
    return {"pdf_path": "main.pdf", "status": "done"}


def _should_design(state: DocumentState) -> Literal["designer_node", "compile_node"]:
    """Route to designer for beamer presentations, skip for articles."""
    doc_type = state.get("doc_type") or "latex_article"
    if doc_type == "latex_beamer":
        return "designer_node"
    return "compile_node"


def create_document_graph(checkpointer: BaseCheckpointSaver):
    workflow = StateGraph(DocumentState)
    workflow.add_node("plan_node", plan_node)
    workflow.add_node("write_node", write_node)
    workflow.add_node("review_node", review_node)
    workflow.add_node("designer_node", designer_node)
    workflow.add_node("compile_node", compile_node)

    workflow.set_entry_point("plan_node")
    workflow.add_edge("plan_node", "write_node")
    workflow.add_edge("write_node", "review_node")

    # Conditional: beamer → designer → compile; article → compile directly
    workflow.add_conditional_edges("review_node", _should_design)

    workflow.add_edge("designer_node", "compile_node")
    workflow.add_edge("compile_node", END)

    return workflow.compile(checkpointer=checkpointer)

