import asyncio
import json
import os
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from zipfile import ZIP_DEFLATED, ZipFile

from .schemas import FileEntry


def ensure_project_dir(projects_root: Path, project_id: str, meta: Dict[str, str]) -> Path:
    project_path = projects_root / project_id
    project_path.mkdir(parents=True, exist_ok=True)
    manifest_path = project_path / "meta.json"
    manifest_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return project_path


async def ensure_project_dir_async(projects_root: Path, project_id: str, meta: Dict[str, str]) -> Path:
    """Async wrapper for ensure_project_dir."""
    return await asyncio.to_thread(ensure_project_dir, projects_root, project_id, meta)


def iter_file_entries(project_path: Path) -> List[FileEntry]:
    entries: List[FileEntry] = []
    ignore_dirs = {".git", ".venv", "__pycache__", ".DS_Store", "node_modules", ".cursor"}
    ignore_files = {".DS_Store", "project.zip", "data.db", "data.db-shm", "data.db-wal"}
    
    for root, dirs, files in os.walk(project_path):
        # Filter directories in-place to prevent recursion
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        rel_root = Path(root).relative_to(project_path)
        for directory in dirs:
            dir_path = (rel_root / directory).as_posix()
            entries.append(
                FileEntry(
                    path=dir_path if dir_path != "." else directory,
                    is_dir=True,
                    size_bytes=0,
                )
            )
        for file in files:
            if file in ignore_files or file.endswith((".pyc", ".pyo")):
                continue
                
            full = Path(root) / file
            rel = (rel_root / file).as_posix()
            entries.append(
                FileEntry(
                    path=rel if rel != "." else file,
                    is_dir=False,
                    size_bytes=full.stat().st_size,
                )
            )
    return entries


async def iter_file_entries_async(project_path: Path) -> List[FileEntry]:
    """Async wrapper for iter_file_entries to avoid blocking the event loop."""
    return await asyncio.to_thread(iter_file_entries, project_path)


def read_project_file(project_path: Path, relative_path: str) -> Tuple[bytes, bool]:
    full_path = (project_path / relative_path).resolve()
    if not str(full_path).startswith(str(project_path.resolve())) or not full_path.exists():
        raise FileNotFoundError(relative_path)
    data = full_path.read_bytes()
    is_text = False
    try:
        data.decode("utf-8")
        is_text = True
    except UnicodeDecodeError:
        is_text = False
    return data, is_text


async def read_project_file_async(project_path: Path, relative_path: str) -> Tuple[bytes, bool]:
    """Async wrapper for read_project_file."""
    return await asyncio.to_thread(read_project_file, project_path, relative_path)


def build_project_zip(project_path: Path) -> Path:
    zip_path = project_path / "project.zip"
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zip_file:
        for file in project_path.rglob("*"):
            if file.is_file() and file.name != "project.zip":
                zip_file.write(file, arcname=file.relative_to(project_path))
    return zip_path


async def build_project_zip_async(project_path: Path) -> Path:
    """Async wrapper for build_project_zip."""
    return await asyncio.to_thread(build_project_zip, project_path)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def write_files(project_path: Path, files: Iterable[Dict[str, str]]) -> List[Path]:
    saved: List[Path] = []
    root = project_path.resolve()
    for file in files:
        relative = file["path"].lstrip("/")
        content = file.get("content", "")
        dest = (project_path / relative).resolve()
        if not _is_within(dest, root):
            # Skip attempts to write outside the project directory
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        saved.append(dest)
    return saved


async def write_files_async(project_path: Path, files: Iterable[Dict[str, str]]) -> List[Path]:
    """Async wrapper for write_files."""
    return await asyncio.to_thread(write_files, project_path, files)
