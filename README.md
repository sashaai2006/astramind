# AstroMind

Virtual AI Company MVP - Monorepo with FastAPI backend and Next.js frontend that simulates a virtual AI company generating MVP artifacts. The backend orchestrates CEO/developer agents, streams logs over WebSocket, manages project files. The frontend visualises file trees, DAG execution, editor, and AI chat.

## Prerequisites

- Python 3.11+
- Node.js 18+

## Quick start

```bash
make init    # install Python packages and frontend dependencies
make dev     # starts uvicorn and next dev together
```

`make dev` spawns both servers; stop them with `Ctrl+C`. During development the backend listens on `http://localhost:8000` and the frontend on `http://localhost:3000`.

### Useful environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PROJECTS_ROOT` | Directory for generated artifacts | `./projects` |
| `LLM_MODE` | `mock`, `ollama`, or `groq` | `mock` |
| `LLM_SEMAPHORE` | Max concurrent LLM calls | `10` |
| `GROQ_API_KEY` | Groq API key (for `groq` mode) | - |

Set `LLM_MODE=groq` to use Groq API (fast inference). Requires `GROQ_API_KEY` environment variable.

## API reference (curl)

Create project:

```bash
curl -X POST http://localhost:8000/api/projects \
  -H "Content-Type: application/json" \
  -d '{"title":"test","description":"demo","target":"web"}'
```

Connect to WebSocket (example with `wscat`):

```bash
wscat -c ws://localhost:8000/ws/projects/<project_id>
```

List files:

```bash
curl http://localhost:8000/api/projects/<project_id>/files
```

Download ZIP:

```bash
curl -OJ http://localhost:8000/api/projects/<project_id>/download
```

### Tests

```bash
source .venv/bin/activate
pytest
```

## Notes

- Projects are stored under `./projects/<project_id>` alongside `meta.json` and cached `project.zip`.
- WebSocket supports `{"type":"command","command":"stop"}` to cancel orchestration.
