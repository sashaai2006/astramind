"""Robust Markdown to LaTeX converter for PDF generation."""

from __future__ import annotations

import re
from typing import List


def escape_latex(text: str) -> str:
    """Escape special LaTeX characters."""
    result = text
    # Escape backslash first (to avoid double-escaping)
    result = result.replace('\\', r'\textbackslash{}')
    # Then escape other special characters
    result = result.replace('&', r'\&')
    result = result.replace('%', r'\%')
    result = result.replace('$', r'\$')
    result = result.replace('#', r'\#')
    result = result.replace('^', r'\textasciicircum{}')
    result = result.replace('_', r'\_')
    result = result.replace('{', r'\{')
    result = result.replace('}', r'\}')
    result = result.replace('~', r'\textasciitilde{}')
    return result


def markdown_to_latex(markdown_text: str, detect_russian: bool = True) -> str:
    """Convert Markdown text to LaTeX format."""
    lines = markdown_text.split('\n')
    latex_lines: List[str] = []
    in_code_block = False
    code_block_lang = None
    code_block_content: List[str] = []
    
    # Detect Russian/Cyrillic
    has_russian = False
    if detect_russian:
        has_russian = any('\u0400' <= c <= '\u04FF' for c in markdown_text)
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Code blocks (```) - handle before other processing
        if line.strip().startswith('```'):
            if in_code_block:
                # End code block - output verbatim content
                latex_lines.append('\\begin{verbatim}')
                # Don't escape code block content - it's verbatim
                latex_lines.extend(code_block_content)
                latex_lines.append('\\end{verbatim}')
                latex_lines.append('')
                code_block_content = []
                in_code_block = False
                code_block_lang = None
            else:
                # Start code block
                code_block_lang = line.strip()[3:].strip()
                in_code_block = True
            i += 1
            continue
        
        if in_code_block:
            # Collect code block lines without processing
            code_block_content.append(line)
            i += 1
            continue
        
        # Headers - extract text and process formatting inside
        if line.startswith('# '):
            header_text = line[2:].strip()
            # Process inline formatting in headers (bold, italic, code)
            header_text = process_inline_formatting(header_text, has_russian)
            latex_lines.append(f'\\section{{{header_text}}}')
            latex_lines.append('')
        elif line.startswith('## '):
            header_text = line[3:].strip()
            header_text = process_inline_formatting(header_text, has_russian)
            latex_lines.append(f'\\subsection{{{header_text}}}')
            latex_lines.append('')
        elif line.startswith('### '):
            header_text = line[4:].strip()
            header_text = process_inline_formatting(header_text, has_russian)
            latex_lines.append(f'\\subsubsection{{{header_text}}}')
            latex_lines.append('')
        elif line.startswith('#### '):
            header_text = line[5:].strip()
            header_text = process_inline_formatting(header_text, has_russian)
            latex_lines.append(f'\\paragraph{{{header_text}}}')
            latex_lines.append('')
        # Horizontal rule
        elif line.strip() == '---' or line.strip() == '***':
            latex_lines.append('\\hrule')
            latex_lines.append('')
        # Empty line = paragraph break
        elif not line.strip():
            latex_lines.append('')
        else:
            # Process inline formatting for regular text
            # First, detect and protect math expressions
            processed_line = detect_and_wrap_math(line)
            # Then process other formatting
            processed_line = process_inline_formatting(processed_line, has_russian)
            if processed_line.strip():
                latex_lines.append(processed_line)
        
        i += 1
    
    # Close any open code block
    if in_code_block:
        latex_lines.append('\\begin{verbatim}')
        latex_lines.extend(code_block_content)
        latex_lines.append('\\end{verbatim}')
    
    return '\n'.join(latex_lines)


def detect_and_wrap_math(line: str) -> str:
    """Detect mathematical expressions and wrap them in $...$."""
    result = line.strip()
    if not result:
        return result
    
    # Protect already wrapped math ($...$) - use placeholders without underscores
    math_blocks = []
    def protect_math(match):
        placeholder = f'<MATHBLOCK{len(math_blocks)}>'
        math_blocks.append((placeholder, match.group(0)))
        return placeholder
    result = re.sub(r'\$[^$]+\$', protect_math, result)
    
    # Detect full equations: pattern like "something = something" where right side has math
    # Match until end of line, comma, period, or semicolon
    # Example: s'(t) = \frac{d}{dt} (t^2) = 2t
    def find_equation_end(text, start):
        """Find where equation ends."""
        i = start
        paren_count = 0
        while i < len(text):
            if text[i] == '(':
                paren_count += 1
            elif text[i] == ')':
                paren_count -= 1
            elif text[i] in [',', '.', ';', '\n'] and paren_count == 0:
                return i
            i += 1
        return len(text)
    
    # Find equations: pattern starts with function call or variable, then =, then math expression
    i = 0
    output_parts = []
    while i < len(result):
        # Look for equation pattern: variable/function = ...
        eq_match = re.search(r'([a-zA-Z]\'?\([^)]+\)|[a-zA-Z][a-zA-Z0-9]*)\s*=\s*', result[i:])
        if eq_match:
            eq_start = i + eq_match.start()
            eq_end = find_equation_end(result, eq_start + len(eq_match.group(0)))
            equation = result[eq_start:eq_end].strip()
            
            # Check if equation contains math (frac, ^, _, operators)
            if '\\frac' in equation or '^' in equation or '_' in equation or any(op in equation for op in ['+', '-', '*', '/']):
                # Wrap entire equation
                output_parts.append(result[i:eq_start])
                output_parts.append(f'${equation}$')
                i = eq_end
                continue
        
        # Look for standalone LaTeX commands
        frac_match = re.search(r'\\frac\{[^}]+\}\{[^}]+\}', result[i:])
        if frac_match:
            frac_start = i + frac_match.start()
            # Check if not already in math mode
            if not (frac_start > 0 and result[frac_start-1] == '$'):
                output_parts.append(result[i:frac_start])
                output_parts.append(f'${frac_match.group(0)}$')
                i = frac_start + len(frac_match.group(0))
                continue
        
        # Look for function calls: f(x), s'(t)
        func_match = re.search(r'\b([a-zA-Z]\'?\([^)]+\))', result[i:])
        if func_match:
            func_start = i + func_match.start()
            # Check if not already in math and not part of equation
            if not (func_start > 0 and result[func_start-1] == '$'):
                # Check if followed by = (part of equation)
                next_chars = result[func_start + len(func_match.group(1)):func_start + len(func_match.group(1)) + 3]
                if '=' not in next_chars:
                    output_parts.append(result[i:func_start])
                    output_parts.append(f'${func_match.group(1)}$')
                    i = func_start + len(func_match.group(1))
                    continue
        
        # Regular character
        output_parts.append(result[i])
        i += 1
    
    result = ''.join(output_parts)
    
    # Restore protected math blocks
    for placeholder, original in math_blocks:
        result = result.replace(placeholder, original)
    
    # Clean up: remove double $, fix spacing
    result = re.sub(r'\$\s*\$', '', result)  # Remove empty math
    result = re.sub(r'\$\$+', '$$', result)  # Fix multiple $
    
    return result


def process_inline_formatting(line: str, has_russian: bool = False) -> str:
    """Process inline Markdown formatting (bold, italic, code, links)."""
    result = line
    
    # Use placeholders without underscores (to avoid escaping issues)
    # Protect math expressions FIRST ($...$) - don't touch anything inside
    protected_math = []
    def protect_math_block(match):
        placeholder = f'<MATH{len(protected_math)}>'
        protected_math.append((placeholder, match.group(0)))
        return placeholder
    result = re.sub(r'\$[^$]+\$', protect_math_block, result)
    
    # Links [text](url) - convert to text only
    result = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', result)
    
    # Images ![alt](url) - skip
    result = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'', result)
    
    # Process formatting: escape content first, then wrap in LaTeX commands
    # Inline code `code` - escape content and wrap
    result = re.sub(r'`([^`]+)`', lambda m: f'\\texttt{{{escape_latex(m.group(1))}}}', result)
    
    # Bold **text** - escape content and wrap
    result = re.sub(r'\*\*([^*]+?)\*\*', lambda m: f'\\textbf{{{escape_latex(m.group(1))}}}', result)
    result = re.sub(r'__([^_]+?)__', lambda m: f'\\textbf{{{escape_latex(m.group(1))}}}', result)
    
    # Italic *text* - escape content and wrap (but not if it's part of **)
    result = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', lambda m: f'\\textit{{{escape_latex(m.group(1))}}}', result)
    result = re.sub(r'(?<!_)_([^_\n]+?)_(?!_)', lambda m: f'\\textit{{{escape_latex(m.group(1))}}}', result)
    
    # Protect LaTeX commands (\command{arg}) - don't escape braces inside
    protected_cmds = []
    def protect_cmd(match):
        placeholder = f'<CMD{len(protected_cmds)}>'
        protected_cmds.append((placeholder, match.group(0)))
        return placeholder
    # Match LaTeX commands with braces - be more careful with nested braces
    # Simple pattern: \command{arg} where arg doesn't contain }
    cmd_pattern = r'\\([a-zA-Z]+\*?)\{([^}]*)\}'
    result = re.sub(cmd_pattern, protect_cmd, result)
    
    # Now escape remaining special characters in plain text
    result = escape_latex(result)
    
    # Restore protected LaTeX commands (they have correct braces)
    for placeholder, original in protected_cmds:
        result = result.replace(placeholder, original)
    
    # Restore protected math blocks (they are already correct)
    for placeholder, original in protected_math:
        result = result.replace(placeholder, original)
    
    return result


def create_latex_document(markdown_files: List[str], titles: List[str], has_russian: bool = True) -> str:
    """Create a complete LaTeX document from multiple Markdown files."""
    # Preamble - tectonic 0.15 runs pdfLaTeX.
    if has_russian:
        # IMPORTANT:
        # - Do NOT use \\usepackage[T2A]{fontenc} with tectonic default bundle (often missing TFM metrics).
        # - Do NOT rely on XeLaTeX (tectonic doesn't run it).
        # This minimal combo compiles with tectonic and supports UTF-8 Cyrillic text.
        preamble = """\\documentclass[12pt,a4paper]{article}
\\usepackage[utf8]{inputenc}
\\usepackage[russian]{babel}
\\usepackage{geometry}
\\geometry{margin=2.5cm}
\\usepackage{hyperref}
\\hypersetup{
    colorlinks=true,
    linkcolor=blue,
    urlcolor=blue,
    pdftitle={Project Documentation}
}
\\setlength{\\parindent}{0pt}
\\setlength{\\parskip}{0.5em}
"""
    else:
        # English/Non-Russian preamble (pdfLaTeX compatible)
        preamble = """\\documentclass[12pt,a4paper]{article}
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}
\\usepackage{geometry}
\\geometry{margin=2.5cm}
\\usepackage{hyperref}
\\hypersetup{
    colorlinks=true,
    linkcolor=blue,
    urlcolor=blue,
    pdftitle={Project Documentation}
}
\\setlength{\\parindent}{0pt}
\\setlength{\\parskip}{0.5em}
"""
    
    body_parts = ["\\begin{document}"]
    body_parts.append("")
    
    # Add title if we have files
    if titles:
        first_title = titles[0] if len(titles) == 1 else "Project Documentation"
        body_parts.append(f"\\title{{{escape_latex(first_title)}}}")
        body_parts.append("\\maketitle")
        body_parts.append("")
    
    # Add table of contents if multiple files
    if len(titles) > 1:
        body_parts.append("\\tableofcontents")
        body_parts.append("\\newpage")
        body_parts.append("")
    
    for title, md_content in zip(titles, markdown_files):
        # Only add section if content doesn't start with a header
        first_line = md_content.strip().split('\n')[0] if md_content.strip() else ""
        if not first_line.startswith('#'):
            body_parts.append(f"\\section{{{escape_latex(title)}}}")
            body_parts.append("")
        
        latex_content = markdown_to_latex(md_content, detect_russian=has_russian)
        body_parts.append(latex_content)
        
        # Add page break between sections (except last)
        if title != titles[-1]:
            body_parts.append("")
            body_parts.append("\\newpage")
            body_parts.append("")
    
    body_parts.append("\\end{document}")
    
    return preamble + "\n".join(body_parts)
