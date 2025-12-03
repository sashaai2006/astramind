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
| `LLM_MODE` | `mock`, `ollama`, `groq`, `github`, `deepseek`, or `cerebras` | `deepseek` |
| `LLM_SEMAPHORE` | Max concurrent LLM calls | `10` |
| `GROQ_API_KEY` | Groq API key (for `groq` mode) | - |
| `GITHUB_TOKEN` | GitHub token (for `github` mode - FREE GPT-4o/Claude!) | - |
| `DEEPSEEK_API_KEY` | DeepSeek API key (for `deepseek` mode - FREE 671B model!) | - |
| `CEREBRAS_API_KEY` | Cerebras API key (for `cerebras` mode - FASTEST inference!) | - |

### Free LLM Options (Recommended!)

**DeepSeek** (Default, Recommended):
- Get free API key: https://platform.deepseek.com/api_keys
- DeepSeek-V3: 671B MoE model, beats GPT-4o on coding
- Free: 10M tokens/day
```bash
export LLM_MODE=deepseek
export DEEPSEEK_API_KEY=your_key_here
```

**GitHub Models** (Best Quality):
- Get token: https://github.com/settings/tokens (classic token)
- Access to GPT-4o, Claude 3.5 Sonnet, Llama 3.1-70B
- Free for developers
```bash
export LLM_MODE=github
export GITHUB_MODEL=gpt-4o  # or claude-3-5-sonnet
export GITHUB_TOKEN=your_token_here
```

**Cerebras** (Fastest):
- Get API key: https://cloud.cerebras.ai/
- World's fastest inference (2000+ tokens/sec)
- Free tier available
```bash
export LLM_MODE=cerebras
export CEREBRAS_API_KEY=your_key_here
```

**Groq** (Fast & Free):
```bash
export LLM_MODE=groq
export GROQ_API_KEY=your_key_here
```

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
