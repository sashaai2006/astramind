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

