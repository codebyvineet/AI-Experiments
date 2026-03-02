# Copilot Instructions

## Architecture

This is a containerized multi-agent AI application with four services orchestrated via Docker Compose:

- **Backend** (`app/`, port 8000) — FastAPI server with LangGraph orchestration, JWT auth, and RBAC. Entry point: `app/main.py`.
- **MCP Server** (`mcp-server/`, port 8001) — Separate FastMCP service exposing CRUD tools via JSON-RPC and streamable-http transports. Entry point: `mcp-server/src/app.py`.
- **Frontend** (`frontend/`, port 3000) — React + Vite + Tailwind SPA.
- **Infrastructure** — MongoDB 7.0 (persistent state, LangGraph checkpoints) and Redis 7 (cache, token blacklist).

The MCP Server **never** accesses the database directly — all data operations go through the Backend API with the user's JWT token, so authorization is enforced at every layer.

### Two AI modes

1. **Plan Mode** — LangGraph `StateGraph` with `interrupt()` for human-in-the-loop approval. Flow: `planner_node → approval_node → executor_dispatch → task_executor_node (parallel via Send()) → step_aggregator → summary`.
2. **Chat Mode** — LangGraph `create_react_agent` for autonomous tool-calling conversations.

### Key module map

| Module | Role |
|---|---|
| `app/agent/graph.py` | LangGraph StateGraph orchestrator |
| `app/agent/state.py` | `AgentState` TypedDict with `Annotated` reducers for parallel accumulation |
| `app/agent/nodes.py` | All graph node implementations |
| `app/agent/react_agent.py` | ReAct agent (Chat Mode) |
| `app/agent/ai_service.py` | Vertex AI / Gemini wrapper |
| `app/api/streaming.py` | SSE endpoints for both modes |
| `app/auth/authorization.py` | JWT + RBAC (roles: admin, user, read_only) |
| `app/mcp/client.py` | `MCPClientWrapper` using `langchain-mcp-adapters` |
| `mcp-server/src/server.py` | `@mcp.tool` definitions (FastMCP) |
| `mcp-server/src/app.py` | FastAPI wrapper mounting FastMCP's HTTP app |

## Build & Run

```bash
# Start all backend services
docker-compose up -d

# Verify health
curl http://localhost:8000/health
curl http://localhost:8001/health

# Start frontend
cd frontend && npm install && npm run dev

# Rebuild backend after code changes
docker-compose build --no-cache app && docker-compose up -d app

# Rebuild MCP server after code changes
docker-compose build --no-cache mcp-server && docker-compose up -d mcp-server

# View backend logs
docker-compose logs -f app
```

### Frontend commands

```bash
cd frontend
npm run dev      # Dev server on :3000
npm run build    # Production build
```

## Environment Setup

Copy `.env.example` to `.env`. Required variables:
- `JWT_SECRET_KEY` — min 32 chars (`python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`)
- `GOOGLE_CLOUD_PROJECT` — GCP project ID with Vertex AI enabled
- Service account JSON in `credentials/service-account.json`

## Conventions

### Backend (Python)

- **Framework**: FastAPI with Pydantic v2 models and `pydantic-settings` for config.
- **Settings**: All config via environment variables, loaded through `app/config/settings.py` (`get_settings()` is `@lru_cache`'d).
- **Auth pattern**: `HTTPBearer` dependency → JWT decode → RBAC permission check. Permissions use `resource:action` format (e.g., `items:write`, `mcp:read`).
- **Logging**: Structured logging with emoji prefixes (📥 request, 📤 response, 🤖 AI, ✅ success, ❌ error). Use `LogContext` from `app/config/logging_config.py`.
- **Middleware**: Custom ASGI middleware (not `BaseHTTPMiddleware`) to avoid blocking SSE streams.
- **LangGraph state**: `AgentState` is a `TypedDict` with `Annotated[List, add]` reducers on `results` and `messages` for safe parallel accumulation.
- **MCP tools**: Defined with `@mcp.tool` decorators in `mcp-server/src/server.py`. Each tool accepts an `auth_token` parameter as fallback, but primarily extracts tokens from HTTP headers via `_extract_token_from_context()`.
- **Async everywhere**: All database operations, API calls, and AI invocations are async. MongoDB uses `motor`, Redis uses `aioredis`-compatible client.

### Frontend (React)

- Plain React 18 with Vite — no TypeScript, no state management library.
- Styling via Tailwind CSS.
- API calls centralized in `frontend/src/api.js`.
- Components in `frontend/src/components/` — one file per panel (AgentPanel, ChatSession, Dashboard, ItemsPanel, McpPanel, Login).

### MCP Server

- Uses FastMCP framework (`fastmcp>=2.0.0`) with `@mcp.tool` decorators.
- Dual transport: JSON-RPC 2.0 at `POST /message` (Plan Mode) and streamable-http at `POST /mcp` (Chat Mode).
- All tool implementations proxy to the Backend API via `httpx` — the MCP server is stateless.

### RBAC roles

| Role | Key permissions |
|---|---|
| `admin` | `users:*`, `items:*`, `agent:*`, `mcp:*` |
| `user` | `items:read/write/delete`, `agent:execute`, `mcp:read/write` |
| `read_only` | `items:read`, `mcp:read` |
