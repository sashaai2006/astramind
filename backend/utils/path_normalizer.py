from __future__ import annotations

from pathlib import Path


def normalize_artifact_path(path: str) -> str:
    """Normalize artifact path so we never emit .txt.

    Rules:
    - If extension is .txt, convert to .md
    - Keep everything else as-is
    """
    p = Path(path)
    if p.suffix.lower() == ".txt":
        return str(p.with_suffix(".md"))
    return path
