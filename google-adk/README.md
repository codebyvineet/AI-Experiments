# Google ADK Implementation

A separate implementation of the MCP Demo application using **Google ADK (Agent Development Kit)** — the best-fit framework for the Gemini stack.

## Why Google ADK?

| Aspect | LangGraph (original) | Google ADK (this impl.) |
|--------|---------------------|------------------------|
| Agent definition | ~280 lines (custom state machine) | ~50 lines (`LlmAgent` + `SequentialAgent`) |
| Session persistence | ~190 lines (custom MongoDB + Redis stores) | `adk-mongodb-session` (3 lines) |
| MCP integration | `langchain-mcp-adapters` | `MCPToolset` (built-in) |
| Gemini model | `ChatVertexAI` (LangChain wrapper) | Native Gemini support |
| Plan mode | 6-node `StateGraph` with `interrupt()` | `SequentialAgent` (planner + executor) |

**Estimated code reduction: ~60–70%** on the agent layer.

## Architecture

```
┌─────────────────────────────────┐     ┌──────────────────────────┐
│  FastAPI App  (port 8000)       │────▶│  MCP Server  (port 8001) │
│                                 │ SSE │                          │
│  ┌─────────────────────────┐   │     │  FastMCP tools:          │
│  │  Google ADK             │   │     │  • list_items            │
│  │  ┌──────────────────┐   │   │     │  • read_item             │
│  │  │  LlmAgent        │   │   │     │  • create_item           │
│  │  │  (chat mode)     │   │   │     │  • update_item           │
│  │  └──────────────────┘   │   │     │  • delete_item           │
│  │  ┌──────────────────┐   │   │     │                          │
│  │  │  SequentialAgent │   │   │     │  JWT RBAC enforced       │
│  │  │  planner+executor│   │   │     │  per tool call           │
│  │  └──────────────────┘   │   │     └──────────────────────────┘
│  └─────────────────────────┘   │
│                                 │     ┌──────────────────────────┐
│  MongoDB session store          │────▶│  MongoDB  (port 27017)   │
│  (adk-mongodb-session)          │     │  • users                 │
│                                 │     │  • items                 │
│  Redis token blacklist          │     │  • agent_sessions        │
│                                 │     │  • adk_* (ADK sessions)  │
└─────────────────────────────────┘     └──────────────────────────┘
                                        ┌──────────────────────────┐
                                        │  Redis  (port 6379)      │
                                        │  • JWT token blacklist   │
                                        └──────────────────────────┘
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- A Google AI API key **or** a Google Cloud project with Vertex AI

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set:
- `JWT_SECRET_KEY` — a random 32+ character secret (`python -c 'import secrets; print(secrets.token_urlsafe(32))'`)
- `GOOGLE_API_KEY` — your Google AI Studio key **or** set up Vertex AI credentials

### 2. Start all services

```bash
docker compose up --build
```

This starts:
| Service | Port | Description |
|---------|------|-------------|
| `app` | 8000 | FastAPI + Google ADK agent |
| `mcp-server` | 8001 | Standalone FastMCP server |
| `mongodb` | 27017 | Session + data store |
| `redis` | 6379 | Token blacklist |

### 3. Register & login

```bash
# Register
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "email": "alice@example.com", "password": "secret", "role": "user"}'

# Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret"}'
# → {"access_token": "eyJ...", "token_type": "bearer"}
```

### 4. Chat mode (ReAct with MCP tools)

```bash
TOKEN="eyJ..."

# Create a session
SESSION=$(curl -s -X POST http://localhost:8000/agent/sessions \
  -H "Authorization: Bearer $TOKEN" | jq -r .session_id)

# Chat with the ADK agent (it can call MCP tools)
curl -X POST http://localhost:8000/agent/sessions/$SESSION/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Create an item called Widget with description Test item"}'
```

### 5. Plan mode

```bash
# Enter plan mode — ADK planner generates a JSON plan
curl -X POST http://localhost:8000/agent/sessions/$SESSION/plan \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"goal": "Create three items and then list them all"}'

# Execute next step
curl -X POST http://localhost:8000/agent/sessions/$SESSION/execute-step \
  -H "Authorization: Bearer $TOKEN"

# Execute all remaining steps
curl -X POST http://localhost:8000/agent/sessions/$SESSION/execute-all \
  -H "Authorization: Bearer $TOKEN"
```

## API Reference

Interactive docs at `http://localhost:8000/docs`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/register` | POST | Register a new user |
| `/auth/login` | POST | Login and get JWT |
| `/auth/me` | GET | Get current user profile |
| `/items/` | POST/GET | Create / list items |
| `/items/{id}` | GET/PUT/DELETE | Read / update / delete item |
| `/agent/sessions` | POST | Create agent session |
| `/agent/sessions/{id}` | GET | Get session state |
| `/agent/sessions/{id}/chat` | POST | Chat mode (ReAct + MCP tools) |
| `/agent/sessions/{id}/plan` | POST | Plan mode — generate plan |
| `/agent/sessions/{id}/execute-step` | POST | Execute next plan step |
| `/agent/sessions/{id}/execute-all` | POST | Execute all plan steps |
| `/agent/sessions/{id}/archive` | POST | Archive session |

## Key Design Decisions

### Google ADK replaces the custom LangGraph agent

The original implementation had a ~280-line hand-rolled state machine
(`langgraph_agent.py`) that only superficially resembled LangGraph.

This implementation uses:
- `LlmAgent` — single-agent chat with MCP tool use
- `SequentialAgent` (planner + executor sub-agents) — for plan mode
- `Runner` — executes agent turns and manages conversation history

### MCP server stays standalone

Per the project constraint, the MCP server runs as a **completely separate
container** (`mcp-server:8001`).  The ADK agent connects to it at runtime
via `MCPToolset(SseConnectionParams(...))`.

### Session persistence: MongoDB via `adk-mongodb-session`

The `MongodbSessionService` from `adk-mongodb-session` stores ADK conversation
history in MongoDB.  Plan state (plan steps, current_step, is_complete) is
additionally mirrored to the `agent_sessions` collection for fast API queries.

State is updated using the ADK event-driven pattern (`append_event` with
`state_delta`) — the recommended approach for auditable, persistent state
changes.

### Redis for JWT token blacklist

Redis is used only for the token blacklist (same pattern as the original
implementation).  Session data is entirely in MongoDB.

## RBAC Roles & Permissions

| Role | Permissions |
|------|-------------|
| `admin` | All permissions |
| `user` | items CRUD + agent execute |
| `read_only` | items read, mcp read |
