from __future__ import annotations

import asyncio
import os
import resource
import signal
from pathlib import Path
from typing import Dict, List, Sequence, Optional

DEFAULT_TIMEOUT = 10
MAX_MEMORY_BYTES = 256 * 1024 * 1024


def _limit_resources() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (DEFAULT_TIMEOUT, DEFAULT_TIMEOUT))
    resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))


async def start_web_server(project_path: Path) -> Dict[str, Any]:
    """Start a web server for HTML/JS projects. Returns process info."""
    # Find entry point - check common locations
    entry_points = [
        project_path / "index.html",
        project_path / "public" / "index.html",
        project_path / "dist" / "index.html",
        project_path / "src" / "index.html",
        project_path / "build" / "index.html",
    ]
    
    # Also check for any index.html recursively
    for html_file in project_path.rglob("index.html"):
        if html_file not in entry_points:
            entry_points.append(html_file)
    
    serve_dir = None
    for entry in entry_points:
        if entry.exists():
            serve_dir = entry.parent
            break
    
    if not serve_dir:
        return {"success": False, "error": "No index.html found in project"}
    
    # Start http.server on a random available port
    import random
    port = random.randint(8080, 8180)
    cmd = ["python3", "-m", "http.server", str(port)]
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(serve_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        # Wait to see if it starts
        await asyncio.sleep(0.5)
        
        if proc.returncode is not None:
            stderr = await proc.stderr.read() if proc.stderr else b""
            return {"success": False, "error": stderr.decode("utf-8")}
        
        return {
            "success": True,
            "pid": proc.pid,
            "url": f"http://localhost:{port}",
            "port": port,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    log_dir: Path,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, object]:
    log_dir.mkdir(parents=True, exist_ok=True)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        preexec_fn=_limit_resources,
    )
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        process.kill()
        stdout, stderr = await process.communicate()

    stdout_path = log_dir / "sandbox_stdout.log"
    stderr_path = log_dir / "sandbox_stderr.log"
    stdout_path.write_bytes(stdout or b"")
    stderr_path.write_bytes(stderr or b"")

    return {
        "exit_code": process.returncode,
        "stdout": stdout.decode("utf-8", errors="ignore"),
        "stderr": stderr.decode("utf-8", errors="ignore"),
        "timed_out": timed_out,
    }


async def execute_safe(
    command: Sequence[str],
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT,
    cwd: Optional[Path] = None,
) -> Dict[str, object]:
    """
    Execute a command safely with resource limits.
    Simplified version for testing purposes.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), 
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout, stderr = await process.communicate()

        return {
            "exit_code": process.returncode,
            "stdout": stdout.decode("utf-8", errors="ignore") if stdout else "",
            "stderr": stderr.decode("utf-8", errors="ignore") if stderr else "",
            "timed_out": timed_out,
        }
    except Exception as e:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
            "timed_out": False,
        }

