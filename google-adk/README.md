# Google ADK — MCP Demo Application

A complete implementation of the MCP Demo application using **Google ADK (Agent Development Kit)** with a React frontend, FastAPI backend, standalone MCP server, and full RBAC authorization.

## Architecture

```
┌─────────────────┐    ┌─────────────────────────────┐    ┌─────────────────────┐
│  React Frontend │───▶│  FastAPI + Google ADK        │───▶│  MCP Server (8001)  │
│  (port 3000)    │    │  (port 8000)                 │    │  FastMCP standalone  │
│                 │    │                               │    │  5 CRUD tools       │
│  • Dashboard    │    │  • Auth (JWT + RBAC)          │    │  JWT RBAC enforced  │
│  • AI Agent     │    │  • Items CRUD API             │    └─────────────────────┘
│  • MCP Server   │    │  • ADK Agent (Chat + Plan)    │
│  • Items CRUD   │    │  • SSE Streaming              │    ┌─────────────────────┐
└─────────────────┘    │                               │───▶│  MongoDB (27017)    │
                       │  InMemorySessionService (ADK)  │    │  users, items,      │
                       │  MongoDB (plan metadata)       │    │  agent_sessions     │
                       │  Redis (token blacklist)       │    └─────────────────────┘
                       └─────────────────────────────────┘    ┌─────────────────────┐
                                                         ───▶│  Redis (6379)       │
                                                              │  JWT token blacklist│
                                                              └─────────────────────┘
```

**5 containers**: Frontend (dev), Backend, MCP Server, MongoDB, Redis

---

## Prerequisites

- **Docker** & **Docker Compose** (v2+)
- **Node.js** 18+ (for frontend dev server)
- **Google Cloud credentials** — one of:
  - A **Google AI API key** from [Google AI Studio](https://aistudio.google.com/apikey) (simplest)
  - A **GCP project** with Vertex AI enabled + service account JSON

---

## Step 1 — Clone & Navigate

```bash
git clone https://github.com/codebyvineet/AI-Experiments.git
cd AI-Experiments/google-adk
```

---

## Step 2 — Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your editor:

```bash
# REQUIRED — Generate a JWT secret:
JWT_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')

# OPTION A: Google AI Studio API key (simplest — no GCP project needed)
GOOGLE_API_KEY=your-google-ai-api-key

# OPTION B: Vertex AI with Service Account
# 1. Place your service account JSON at: credentials/service-account.json
# 2. Set these:
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/service-account.json
GOOGLE_GENAI_USE_VERTEXAI=TRUE
```

> **Tip:** If using Vertex AI, make sure the service account JSON is at  
> `google-adk/credentials/service-account.json` — Docker mounts this path.

---

## Step 3 — Start Backend Services

```bash
docker compose up --build -d
```

This starts 4 containers:

| Service | Port | Description |
|---------|------|-------------|
| `app` | 8000 | FastAPI backend + Google ADK agent |
| `mcp-server` | 8001 | Standalone FastMCP server (5 CRUD tools) |
| `mongodb` | 27017 | MongoDB 7.0 — users, items, sessions |
| `redis` | 6379 | Redis 7 — JWT token blacklist |

**Verify everything is healthy:**

```bash
curl http://localhost:8000/health
# → {"status":"healthy","framework":"google-adk","mongodb":"connected","redis":"connected"}
```

---

## Step 4 — Start Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend starts at **http://localhost:3000** with hot-reload.

> The Vite dev server proxies API requests (`/auth`, `/items`, `/agent`, `/health`, `/mcp`) to `localhost:8000`.

---

## Step 5 — Create Users & Login

### Option A: Via UI

1. Open **http://localhost:3000** in your browser
2. Click **Register** → fill in username, email, password, and role
3. After registration, sign in with your credentials

### Option B: Via CLI

```bash
# Register an admin user
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "email": "admin@test.com", "password": "admin123456", "role": "admin"}'

# Register a read-only user (for testing RBAC)
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "viewer", "email": "viewer@test.com", "password": "viewer123456", "role": "read_only"}'

# Login and get token
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123456"}'
# → {"access_token": "eyJ...", "token_type": "bearer", "user": {...}}
```

---

## Features & How to Use

### 📊 Dashboard

Shows system health (MongoDB, Redis status), current user info, and RBAC permissions for your role.

### 💬 Chat Mode (AI Agent)

1. Go to **AI Agent** tab → click **+ New Session**
2. Make sure **💬 Chat Mode** is selected
3. Type a message like: `"List all items"` or `"Create an item called Widget"`
4. The AI agent uses **Gemini** and calls **MCP tools** to interact with items
5. You'll see:
   - 🔧 **Tool call** badges showing which tool was called and its arguments
   - ✅ **Tool result** badges (click to expand the raw response)
   - The AI's text response

**CLI equivalent:**
```bash
TOKEN="eyJ..."

SESSION=$(curl -s -X POST http://localhost:8000/agent/sessions \
  -H "Authorization: Bearer $TOKEN" | jq -r .session_id)

# Regular chat
curl -X POST http://localhost:8000/agent/sessions/$SESSION/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "List all items"}'

# SSE streaming chat (used by frontend)
curl -N -X POST http://localhost:8000/agent/sessions/$SESSION/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Create an item called Widget"}'
```

### 📋 Plan Mode (AI Agent)

1. Go to **AI Agent** tab → click **+ New Session**
2. Switch to **📋 Plan Mode**
3. Enter a goal like: `"List all items and create one called Plan Widget"`
4. The AI generates a step-by-step plan
5. Click **▶ Execute Next Step** to run one step, or **⏩ Execute All** to run all

**CLI equivalent:**
```bash
# Generate a plan
curl -X POST http://localhost:8000/agent/sessions/$SESSION/plan \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"goal": "Create three items and list them all"}'

# Execute next step
curl -X POST http://localhost:8000/agent/sessions/$SESSION/execute-step \
  -H "Authorization: Bearer $TOKEN"

# Execute all remaining steps
curl -X POST http://localhost:8000/agent/sessions/$SESSION/execute-all \
  -H "Authorization: Bearer $TOKEN"
```

### 🔌 MCP Server Tools

Shows all tools exposed by the standalone MCP server. Click a tool to see its parameters. These tools are automatically available to the AI agent during Chat and Plan modes.

### 📦 Items CRUD

Full create, read, update, delete for items. Role-based:
- **admin** / **user** — can create, edit, and delete items
- **read_only** — can only view items (Edit/Delete buttons hidden, warning banner shown)

---

## RBAC Roles & Permissions

| Role | Permissions |
|------|-------------|
| `admin` | `users:*`, `items:*`, `agent:*`, `mcp:*` |
| `user` | `items:read/write/delete`, `agent:execute`, `mcp:read/write` |
| `read_only` | `items:read`, `mcp:read` |

To see your permissions: Dashboard → **🔐 Permissions** section.

---

## API Reference

Interactive Swagger docs: **http://localhost:8000/docs**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | System health (MongoDB, Redis, framework) |
| `/auth/register` | POST | Register a new user |
| `/auth/login` | POST | Login → JWT access token |
| `/auth/me` | GET | Current user profile |
| `/auth/permissions/{role}` | GET | List permissions for a role |
| `/items/` | GET | List all items |
| `/items/` | POST | Create item |
| `/items/{id}` | GET/PUT/DELETE | Read / update / delete item |
| `/mcp/tools` | GET | List MCP server tools |
| `/agent/sessions` | GET | List agent sessions |
| `/agent/sessions` | POST | Create new agent session |
| `/agent/sessions/{id}` | GET | Get session state |
| `/agent/sessions/{id}/chat` | POST | Chat mode (non-streaming) |
| `/agent/sessions/{id}/chat/stream` | POST | Chat mode (SSE streaming) |
| `/agent/sessions/{id}/plan` | POST | Plan mode — generate plan |
| `/agent/sessions/{id}/execute-step` | POST | Execute next plan step |
| `/agent/sessions/{id}/execute-all` | POST | Execute all remaining steps |
| `/agent/sessions/{id}/archive` | POST | Archive session |

---

## Troubleshooting

### Backend won't start

```bash
# Check logs
docker compose logs -f app

# Common: missing .env or credentials
# Make sure .env exists and has JWT_SECRET_KEY set
```

### MCP server errors

```bash
docker compose logs -f mcp-server

# If import error: the Docker image may need rebuild
docker compose build --no-cache mcp-server && docker compose up -d mcp-server
```

### Agent doesn't call tools

The agent needs valid Google AI credentials to work. Check:
1. `GOOGLE_API_KEY` is set in `.env` (Option A), **or**
2. `credentials/service-account.json` exists and `GOOGLE_GENAI_USE_VERTEXAI=TRUE` is set (Option B)

```bash
# Test if Gemini is reachable
docker compose logs app | grep -i "error\|gemini\|vertex"
```

### Frontend proxy errors

If API calls from the frontend return 502/504:
1. Make sure the backend is running: `curl http://localhost:8000/health`
2. The Vite proxy config is in `frontend/vite.config.js`

### Rebuild after code changes

```bash
# Backend
docker compose build --no-cache app && docker compose up -d app

# MCP Server
docker compose build --no-cache mcp-server && docker compose up -d mcp-server

# Frontend (auto-reloads with npm run dev — no rebuild needed)
```

---

## Project Structure

```
google-adk/
├── app/                          # FastAPI backend
│   ├── main.py                   # App entry point, health, MCP tools
│   ├── agent/
│   │   └── adk_agent.py          # Google ADK agent (chat + plan modes)
│   ├── api/
│   │   ├── agent_routes.py       # /agent/* endpoints
│   │   ├── auth_routes.py        # /auth/* endpoints
│   │   └── item_routes.py        # /items/* endpoints
│   ├── auth/
│   │   └── authorization.py      # JWT + RBAC
│   ├── config/
│   │   └── settings.py           # Pydantic settings from env
│   └── models/                   # Pydantic models
├── mcp-server/                   # Standalone MCP server (separate container)
│   ├── src/
│   │   ├── app.py                # FastAPI wrapper for FastMCP
│   │   └── server.py             # @mcp.tool definitions
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                     # React + Vite + Tailwind
│   ├── src/
│   │   ├── App.jsx               # Main app with tabs
│   │   ├── api.js                # API client
│   │   └── components/
│   │       ├── Login.jsx          # Login / Register
│   │       ├── Dashboard.jsx      # Health, user info, permissions
│   │       ├── AgentPanel.jsx     # Chat Mode + Plan Mode
│   │       ├── McpPanel.jsx       # MCP tool listing
│   │       └── ItemsPanel.jsx     # Items CRUD
│   ├── package.json
│   └── vite.config.js
├── credentials/                  # Service account JSON (gitignored)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md                     # ← You are here
```

---

## Key Design Decisions

- **Google ADK** replaces LangGraph — `LlmAgent` for chat, plan mode uses a planner agent that generates JSON steps executed sequentially
- **MCP server is standalone** — runs as a separate Docker container, the ADK agent connects via SSE transport
- **InMemorySessionService** for ADK conversation state (fast, no external dependency issues); plan metadata persisted to MongoDB `agent_sessions` collection
- **Auth token injection** — the user's JWT is passed to the agent which forwards it to MCP tools for RBAC enforcement
- **SSE streaming** for real-time chat — tool calls, results, and text are streamed as they happen
