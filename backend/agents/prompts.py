from typing import List, Dict, Any, Optional
import json

from backend.core.presets import get_preset_by_id


class PromptBuilder:
    """Helper to build modular prompts for agents."""

    @staticmethod
    def _persona_block(preset_id: str = "", persona_override: str = "") -> str:
        """Resolve persona prompt from presets, plus optional override."""
        blocks: List[str] = []
        if persona_override and persona_override.strip():
            blocks.append(persona_override.strip())
            blocks.append("")  # spacer

        persona_block = ""
        if preset_id:
            preset = get_preset_by_id(preset_id)
            if preset:
                persona_block = f"{preset.persona_prompt}\n"
            else:
                # Fallback: use preset_id as a simple persona string
                persona_block = f"Persona: {preset_id}\n"
        if persona_block.strip():
            blocks.append(persona_block.strip())

        return "\n".join(b for b in blocks if b is not None)

    @staticmethod
    def build_developer_system_prompt(preset_id: str = "", persona_override: str = "") -> str:
        """Build system prompt, injecting persona from presets config if available."""
        return (
            (PromptBuilder._persona_block(preset_id, persona_override) + "\n" if (preset_id or persona_override) else "")
            + "You are a LEGENDARY SOFTWARE ENGINEER.\n"
            "You have mastered Computer Science fundamentals:\n"
            "- Algorithms & Data Structures\n"
            "- Clean Code & Software Architecture\n"
            "- SOLID principles, Design Patterns\n"
            "- Writing code that COMPILES, RUNS, and is MAINTAINABLE\n"
            "\n"
            "You write code in ANY language with equal mastery.\n"
            "You follow the idioms and best practices of whatever technology is requested.\n"
        )

    @staticmethod
    def build_writer_system_prompt(preset_id: str = "", persona_override: str = "") -> str:
        return (
            (PromptBuilder._persona_block(preset_id, persona_override) + "\n" if (preset_id or persona_override) else "")
            + "You are a WORLD-CLASS TECHNICAL WRITER.\n"
            "You produce clear, structured, example-driven documentation.\n"
            "You use Markdown expertly (headings, lists, code fences, tables when helpful).\n"
            "You are extremely careful about correctness and internal consistency.\n"
        )

    @staticmethod
    def build_latex_system_prompt(preset_id: str = "", persona_override: str = "") -> str:
        return (
            (PromptBuilder._persona_block(preset_id, persona_override) + "\n" if (preset_id or persona_override) else "")
            + "You are a PROFESSIONAL LaTeX WRITER.\n"
            "You write clean, minimal LaTeX that compiles with tectonic.\n"
            "Avoid exotic packages; prefer standard LaTeX packages.\n"
            "For Russian text, write UTF-8 Cyrillic directly and avoid T2A fontenc.\n"
        )

    @staticmethod
    def _infer_mode_from_files(files_spec: List[Dict[str, Any]]) -> str:
        """Infer whether this step is code vs markdown writing vs LaTeX writing."""
        paths: List[str] = []
        for f in files_spec or []:
            p = f.get("path")
            if isinstance(p, str) and p.strip():
                paths.append(p.strip().lower())
        if not paths:
            return "code"
        if all(p.endswith(".md") for p in paths):
            return "md"
        if all(p.endswith(".tex") for p in paths):
            return "tex"
        return "code"

    @staticmethod
    def build_project_context(context: Dict[str, Any], tech_stack: str) -> str:
        return (
            f"=== PROJECT ===\n"
            f"Title: {context.get('title')}\n"
            f"Description: {context.get('description')}\n"
            f"Target: {context.get('target')}\n"
            f"Tech Stack: {tech_stack}\n"
        )

    @staticmethod
    def build_research_context(context: Dict[str, Any]) -> str:
        payload = context.get("research_results")
        if not isinstance(payload, dict):
            return ""
        try:
            q = str(payload.get("query", "")).strip()
            provider = str(payload.get("provider", "")).strip()
            results = payload.get("results", []) or []
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
                    lines.append(f"  {snippet[:180]}")
            body = "\n".join(lines).strip()
            if not (q or body):
                return ""
            return (
                "=== WEB RESEARCH (USE FOR CURRENT BEST PRACTICES) ===\n"
                + (f"Query: {q}\n" if q else "")
                + (f"Provider: {provider}\n" if provider else "")
                + (body + "\n" if body else "")
            )
        except Exception:
            return ""

    @staticmethod
    def build_task_description(step_name: str, files_spec: List[Dict[str, Any]]) -> str:
        spec_json = json.dumps(files_spec, indent=2)
        return (
            f"=== CURRENT TASK: {step_name} ===\n"
            f"Generate code for the following files:\n{spec_json}\n"
        )

    @staticmethod
    def build_quality_standards() -> str:
        return (
            "=== UNIVERSAL CODE QUALITY STANDARDS ===\n"
            "1. COMPLETE: Every function fully implemented. No stubs, no TODOs.\n"
            "2. CORRECT: Code must compile/parse and run without errors.\n"
            "3. CLEAN: Readable, well-structured, meaningful names.\n"
            "4. SAFE: Handle errors appropriately for the language.\n"
            "5. IDIOMATIC: Follow the conventions of the requested technology.\n"
        )

    @staticmethod
    def build_verification_checklist() -> str:
        return (
            "=== BEFORE SUBMITTING ===\n"
            "1. VERIFY: All imports/includes/dependencies declared?\n"
            "2. VERIFY: Entry point exists and is correct for the stack?\n"
            "3. VERIFY: Syntax is valid (matching braces, proper delimiters)?\n"
            "4. VERIFY: All functions/methods are complete (not empty)?\n"
            "5. MENTALLY EXECUTE: Trace through - would it work?\n"
        )

    @staticmethod
    def build_output_format() -> str:
        return (
            "=== OUTPUT FORMAT (JSON) ===\n"
            "{\n"
            '  "_thought": "My reasoning: 1) Task requires X, 2) I need to implement Y...",\n'
            '  "files": [\n'
            '    {"path": "filename.ext", "content": "COMPLETE CODE with \\\\n for newlines"}\n'
            '  ]\n'
            "}\n"
            "\n"
            "=== JSON RULES ===\n"
            "• Newlines → \\n\n"
            "• Quotes → \\\"\n"  
            "• Backslashes → \\\\\n"
            "• content = STRING (not object)\n"
            "• No markdown inside JSON\n"
            "• CRITICAL: NEVER output .txt files (use .md instead)\n"
            "\n"
            "RETURN ONLY JSON."
        )

    @staticmethod
    def assemble_prompt(
        context: Dict[str, Any],
        step: Dict[str, Any],
        files_spec: List[Dict[str, Any]],
        feedback: List[str] = [],
        project_context: str = "",
        knowledge_context: str = ""
    ) -> str:
        payload = step.get("payload", {})
        tech_stack = payload.get("tech_stack", "").strip() or context.get("tech_stack", "")
        persona = payload.get("agent_preset") or context.get("agent_preset") or ""
        persona_override = payload.get("persona_prompt") or context.get("persona_prompt") or ""
        mode = PromptBuilder._infer_mode_from_files(files_spec)

        parts = [
            PromptBuilder.build_writer_system_prompt(str(persona), str(persona_override))
            if mode == "md"
            else PromptBuilder.build_latex_system_prompt(str(persona), str(persona_override))
            if mode == "tex"
            else PromptBuilder.build_developer_system_prompt(str(persona), str(persona_override)),
            PromptBuilder.build_project_context(context, tech_stack),
            PromptBuilder.build_research_context(context),
            f"=== EXISTING FILES (CONTEXT) ===\n{project_context}" if project_context else "",
            f"=== KNOWLEDGE BASE (BEST PRACTICES) ===\n{knowledge_context}" if knowledge_context else "",
            PromptBuilder.build_task_description(step.get("name"), files_spec),
            PromptBuilder.build_quality_standards(),
            PromptBuilder.build_verification_checklist(),
        ]

        if feedback:
            feedback_str = "\n".join(f"- {f}" for f in feedback)
            parts.append(f"=== FEEDBACK FROM REVIEWER (FIX THESE) ===\n{feedback_str}")

        parts.append(PromptBuilder.build_output_format())

        return "\n\n".join(part for part in parts if part)

