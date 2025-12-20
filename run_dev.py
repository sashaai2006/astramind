#!/usr/bin/env python3
"""
Development server launcher for AstraMind.
Starts both backend (FastAPI) and frontend (Next.js) servers.
"""

import os
import sys
import subprocess
import signal
import time
from pathlib import Path

# Colors for terminal output
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

def print_colored(message: str, color: str = RESET):
    print(f"{color}{message}{RESET}")

def check_dependencies():
    """Check if required dependencies are installed."""
    issues = []
    
    # Check Python packages
    try:
        import uvicorn
        import fastapi
    except ImportError:
        issues.append("Python dependencies not installed. Run: pip install -r requirements.txt")
    
    # Check Node.js and npm
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
        subprocess.run(["npm", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        issues.append("Node.js and npm are required. Please install them.")
    
    # Check frontend dependencies
    frontend_dir = Path(__file__).parent / "frontend" / "src"
    if not (frontend_dir / "node_modules").exists():
        issues.append("Frontend dependencies not installed. Run: cd frontend/src && npm install")
    
    return issues

def start_backend():
    """Start the FastAPI backend server."""
    print_colored("🚀 Starting backend server on http://localhost:8000", GREEN)
    base_dir = Path(__file__).parent.resolve()
    backend_dir = base_dir / "backend"
    
    # IMPORTANT:
    # We must prevent auto-reload from reacting to generated artifacts under
    # 'projects/' and DB churn under 'data/' (LangGraph checkpoints, SQLite WAL).
    # Uvicorn/watchfiles matches reload-exclude patterns against full paths, and
    # patterns like "projects/*" do NOT match nested files (e.g. projects/<id>/main.py),
    # so we use "**" globs.
    cmd = [
        sys.executable, "-m", "uvicorn", "backend.main:app",
        "--host", "0.0.0.0", "--port", "8000", "--reload",
        "--reload-dir", str(backend_dir),
    ]
    
    # Still add excludes as a safety measure
    reload_excludes = [
        # Exclude runtime dirs outside backend; use relative patterns (cwd=backend/)
        "../projects/**",
        "../data/**",
        "../documents/**",
        # Also keep commonly noisy globs (relative patterns for safety)
        "projects/**",
        "data/**",
        "documents/**",
        "**/*.db*",
        "**/__pycache__/**",
        "**/.venv/**",
        "**/.next/**",
        "**/node_modules/**",
    ]
    
    for exclude in reload_excludes:
        cmd.extend(["--reload-exclude", exclude])
    
    backend_process = subprocess.Popen(
        cmd,
        cwd=backend_dir, # Run from backend directory so WatchFiles watches only backend; keep PYTHONPATH set to base_dir so 'backend.*' imports still resolve
        env={**os.environ, "PYTHONPATH": str(base_dir)},
    )
    return backend_process

def start_frontend():
    """Start the Next.js frontend server."""
    print_colored("🚀 Starting frontend server on http://localhost:3000", GREEN)
    frontend_dir = Path(__file__).parent / "frontend" / "src"
    frontend_process = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=frontend_dir,
        env={**os.environ, "NEXT_PUBLIC_API_BASE_URL": "http://localhost:8000"},
    )
    return frontend_process

def main():
    """Main entry point."""
    print_colored("=" * 60, GREEN)
    print_colored("AstraMind Development Server", GREEN)
    print_colored("=" * 60, GREEN)
    
    # Check dependencies
    issues = check_dependencies()
    if issues:
        print_colored("\n⚠️  Issues found:", YELLOW)
        for issue in issues:
            print_colored(f"  - {issue}", YELLOW)
        print_colored("\nPlease fix these issues before starting the servers.\n", RED)
        sys.exit(1)
    
    processes = []
    
    def cleanup(signum, frame):
        """Cleanup function to stop all processes."""
        print_colored("\n\n🛑 Shutting down servers...", YELLOW)
        for process in processes:
            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            except Exception as e:
                print_colored(f"Error stopping process: {e}", RED)
        print_colored("✅ Servers stopped.", GREEN)
        sys.exit(0)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    
    try:
        # Start backend
        backend_process = start_backend()
        processes.append(backend_process)
        
        # Wait a bit for backend to start
        time.sleep(2)
        
        # Start frontend
        frontend_process = start_frontend()
        processes.append(frontend_process)
        
        print_colored("\n✅ Both servers are starting...", GREEN)
        print_colored("📝 Backend API: http://localhost:8000", GREEN)
        print_colored("📝 Backend Docs: http://localhost:8000/docs", GREEN)
        print_colored("🌐 Frontend: http://localhost:3000", GREEN)
        print_colored("\nPress Ctrl+C to stop all servers.\n", YELLOW)
        
        # Wait for processes
        while True:
            # Check if processes are still running
            for i, process in enumerate(processes):
                if process.poll() is not None:
                    print_colored(f"\n⚠️  Process {i} exited with code {process.returncode}", RED)
                    cleanup(None, None)
            time.sleep(1)
            
    except KeyboardInterrupt:
        cleanup(None, None)
    except Exception as e:
        print_colored(f"\n❌ Error: {e}", RED)
        cleanup(None, None)

if __name__ == "__main__":
    main()

