from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from backend.api import projects, websocket
from backend.core.orchestrator import orchestrator
from backend.memory.db import init_db, async_session_factory
from backend.memory.models import Task
from backend.settings import get_settings
from backend.utils.logging import configure_logging, get_logger

LOGGER = get_logger(__name__)
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    get_settings()
    await init_db()
    
    # Optimization: Cleanup "zombie" tasks that were left running when server died
    try:
        async with async_session_factory() as session:
            # Using execute since it's standard SQLAlchemy AsyncSession
            statement = select(Task).where(Task.status == "running")
            result = await session.execute(statement)
            zombies = result.scalars().all()
            
            if zombies:
                LOGGER.warning("Found %d zombie tasks. Resetting to 'failed'.", len(zombies))
                for task in zombies:
                    task.status = "failed"
                    task.result = "Server restarted during execution"
                    session.add(task)
                await session.commit()
    except Exception as e:
        LOGGER.error("Failed to cleanup zombie tasks: %s", e)

    yield
    # Shutdown logic here if needed
    await orchestrator.shutdown()


app = FastAPI(
    title="AI Company Backend", 
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def check_api_key(request: Request, call_next):
    settings = get_settings()
    # Only enforce if key is set and path starts with /api (exclude docs/websocket/static)
    if settings.admin_api_key and request.url.path.startswith("/api"):
        api_key = request.headers.get("X-API-Key")
        if api_key != settings.admin_api_key:
            # Allow OPTIONS for CORS
            if request.method == "OPTIONS":
                return await call_next(request)
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or missing API Key"},
            )
    return await call_next(request)

# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    LOGGER.error("Global exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "error": str(exc)},
    )

app.include_router(projects.router)
app.include_router(websocket.router)
