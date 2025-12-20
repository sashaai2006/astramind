"""File utilities for project operations."""
import asyncio
import json
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
import os

class FileEntry:
    """Represents a file entry in a project."""
    def __init__(self, path: str, is_dir: bool = False):
        self.path = path
        self.is_dir = is_dir

def iter_file_entries(project_path: Path) -> List[FileEntry]:
    """Iterate over all files in a project directory."""
    from backend.utils.logging import get_logger
    logger = get_logger(__name__)
    
    entries = []
    if not project_path.exists():
        logger.warning("iter_file_entries: project_path does not exist: %s", project_path)
        return entries
    
    logger.debug("iter_file_entries: scanning %s", project_path)
    for root, dirs, files in os.walk(project_path):
        root_path = Path(root)
        rel_root = root_path.relative_to(project_path)
        
        for d in dirs:
            if d.startswith('.'):
                continue
            entries.append(FileEntry(str(rel_root / d), is_dir=True))
        
        for f in files:
            if f.startswith('.'):
                continue
            entries.append(FileEntry(str(rel_root / f), is_dir=False))
    
    logger.debug("iter_file_entries: found %d entries in %s", len(entries), project_path)
    return entries

def read_project_file(project_path: Path, file_path: str) -> Tuple[bytes, bool]:
    """Read a file from a project. Returns (data, is_text)."""
    full_path = project_path / file_path
    if not full_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    try:
        data = full_path.read_bytes()
        # Simple text detection
        try:
            data.decode('utf-8')
            is_text = True
        except UnicodeDecodeError:
            is_text = False
        return data, is_text
    except Exception as e:
        raise IOError(f"Error reading file {file_path}: {e}")

def ensure_project_dir(root: Path, project_id: str, metadata: Optional[Dict[str, Any]] = None) -> Path:
    """Ensure project directory exists and optionally save metadata."""
    project_path = root / project_id
    project_path.mkdir(parents=True, exist_ok=True)
    
    if metadata:
        metadata_path = project_path / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
    
    return project_path

def write_files(project_path: Path, files: List[Dict[str, str]]) -> Optional[List[Path]]:
    from backend.utils.logging import get_logger
    logger = get_logger(__name__)
    
    saved = []
    project_root = project_path.resolve()
    
    logger.info("write_files: project_root=%s, files_count=%d", project_root, len(files))
    
    for file_info in files:
        file_path = file_info.get("path")
        content = file_info.get("content")
        
        if not file_path:
            logger.warning("Skipping file with empty path")
            continue
            
        if content is None:
            logger.warning("Skipping file %s with None content", file_path)
            continue
            
        full_path = (project_root / file_path).resolve()
        
        if not str(full_path).startswith(str(project_root)):
            logger.error("Path traversal detected: %s not in %s", full_path, project_root)
            return None
        
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding='utf-8')
        saved.append(full_path)
        logger.info("File saved: %s (%d bytes)", full_path, len(content))
    
    logger.info("write_files completed: %d files saved", len(saved))
    return saved if saved else None

async def write_files_async(project_path: Path, files: List[Dict[str, str]]) -> Optional[List[Path]]:
    """Write multiple files to a project directory asynchronously."""
    return await asyncio.to_thread(write_files, project_path, files)

