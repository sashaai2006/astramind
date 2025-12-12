#!/usr/bin/env python3
"""Launch backend and frontend servers concurrently."""
import asyncio
import os
import signal
import sys
from pathlib import Path

# Load .env file if exists
def load_env():
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        print(f"✓ Loading environment from .env")
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    key, sep, value = line.partition("=")
                    if sep:
                        os.environ[key.strip()] = value.strip()

async def main():
    """Run backend and frontend in parallel."""
    procs = []
    script_dir = Path(__file__).parent
    venv_bin = script_dir / ".venv" / "bin"
    
    # Backend - use uvicorn from venv
    # IMPORTANT: Exclude projects/ folder from watchfiles to prevent restarts during generation
    uvicorn_path = venv_bin / "uvicorn"
    if not uvicorn_path.exists():
        print("Error: Virtual environment not found. Run 'make init' first.")
        sys.exit(1)
    backend_cmd = [
        str(uvicorn_path), 
        "backend.main:app", 
        "--reload",
        "--reload-dir", "backend",  # Watch ONLY backend folder, ignore projects/
    ]
    procs.append(await asyncio.create_subprocess_exec(*backend_cmd))
    
    # Frontend
    frontend_dir = script_dir / "frontend" / "src"
    frontend_cmd = ["npm", "run", "dev"]
    procs.append(await asyncio.create_subprocess_exec(
        *frontend_cmd, cwd=str(frontend_dir)
    ))
    
    print("Backend: http://localhost:8000")
    print("Frontend: http://localhost:3000")
    print("Press Ctrl+C to stop both servers")
    
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    
    def signal_handler():
        print("\nShutting down...")
        stop_event.set()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    await stop_event.wait()
    
    for proc in procs:
        proc.terminate()
    
    await asyncio.gather(*[proc.wait() for proc in procs], return_exceptions=True)
    print("Servers stopped")

if __name__ == "__main__":
    load_env()  # Load .env before starting
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
