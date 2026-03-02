# System Architecture

This document describes the architecture of the AI Experiments MCP Demo Application.

## Quick Reference

| Component | Port | Technology | Purpose |
|-----------|------|------------|---------|
| Frontend | 3000 | React + Vite | User interface |
| Backend | 8000 | FastAPI | API server, AI orchestration |
| MCP Server | 8001 | Python + MCP SDK | Tool execution via MCP protocol |
| MongoDB | 27017 | MongoDB | Hot state storage |
| Redis | 6379 | Redis | Cold state cache |

### Key Files

| File | Purpose |
|------|---------|
| `app/agent/ai_service.py` | Vertex AI integration, plan generation |
| `app/agent/multi_agent.py` | Plan execution orchestration |
| `app/auth/authorization.py` | RBAC permission definitions |
| `mcp-server/src/tools/item_tools.py` | MCP tool implementations |
| `frontend/src/components/AgentPanel.jsx` | AI agent UI |

### RBAC Roles

| Role | Permissions | Use Case |
|------|-------------|----------|
| `admin` | Full access (`*:*`) | System administrators |
| `user` | CRUD items, run agent | Regular users |
| `read_only` | View only | Viewers, auditors |

### Demo Users

```
admin_demo@test.com / admin123   → Full access
user_demo@test.com / user123     → CRUD items
viewer_demo@test.com / viewer123 → Read only
```

### Logging (Grepable)

```bash
docker logs ai-experiments-app-1 | grep "\[AIFLOW\]"
```

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                    FRONTEND                                         │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │                         React UI (Port 3000)                                   │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐                   │ │
│  │  │Dashboard │  │AI Agent  │  │MCP Server│  │  Items CRUD  │                   │ │
│  │  │  Panel   │  │  Panel   │  │  Panel   │  │    Panel     │                   │ │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘                   │ │
│  │       │              │             │               │                           │ │
│  │       └──────────────┴─────────────┴───────────────┘                           │ │
│  │                              │                                                  │ │
│  │                    HTTP/SSE Requests                                           │ │
│  └──────────────────────────────┼──────────────────────────────────────────────────┘ │
└─────────────────────────────────┼────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              BACKEND (Port 8000)                                     │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │                         FastAPI Application                                     │ │
│  │                                                                                 │ │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │  │                    Request Logging Middleware                           │   │ │
│  │  │  • Logs all incoming requests with request ID                           │   │ │
│  │  │  • Tracks response time and status                                      │   │ │
│  │  │  • Adds X-Request-ID header to responses                                │   │ │
│  │  └─────────────────────────────────────────────────────────────────────────┘   │ │
│  │                                    │                                            │ │
│  │  ┌─────────────────────────────────┴───────────────────────────────────────┐   │ │
│  │  │                           API Routers                                   │   │ │
│  │  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │   │ │
│  │  │  │  /auth   │  │ /items   │  │ /agent   │  │  /mcp    │  │ /stream  │   │   │ │
│  │  │  │          │  │          │  │          │  │          │  │   (SSE)  │   │   │ │
│  │  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │   │ │
│  │  └───────┴─────────────┴─────────────┴─────────────┴─────────────┴─────────┘   │ │
│  │                                                                                 │ │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │  │                      Authorization Layer                                │   │ │
│  │  │  • JWT Token Validation                                                 │   │ │
│  │  │  • Role-Based Access Control (admin, user, read_only)                   │   │ │
│  │  │  • Permission Checking (items:read/write/delete, agent:*, mcp:*)        │   │ │
│  │  └─────────────────────────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                      │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │                         Multi-Agent Orchestrator                               │ │
│  │                                                                                 │ │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │  │                        AI Service (Vertex AI)                           │   │ │
│  │  │  • generate_plan() - AI-powered plan generation                         │   │ │
│  │  │  • execute_task() - AI-powered task execution                           │   │ │
│  │  │  • analyze_for_mcp() - Determine which MCP tools to use                 │   │ │
│  │  │  • generate_summary() - AI-powered execution summary                    │   │ │
│  │  └─────────────────────────────────────────────────────────────────────────┘   │ │
│  │                                    │                                            │ │
│  │  ┌─────────────────────────────────┴───────────────────────────────────────┐   │ │
│  │  │                     Agent Types & Execution Modes                       │   │ │
│  │  │                                                                         │   │ │
│  │  │  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐   │   │ │
│  │  │  │ Research Agent   │    │ Execution Agent  │    │ Validation Agent │   │   │ │
│  │  │  │ (can run in      │    │ (sequential      │    │ (sequential      │   │   │ │
│  │  │  │  parallel)       │    │  execution)      │    │  execution)      │   │   │ │
│  │  │  └──────────────────┘    └──────────────────┘    └──────────────────┘   │   │ │
│  │  │                                                                         │   │ │
│  │  │  Execution Modes:                                                       │   │ │
│  │  │  • PARALLEL: Multiple tasks run concurrently (e.g., research phase)     │   │ │
│  │  │  • SEQUENTIAL: Tasks run one after another (e.g., execution phase)      │   │ │
│  │  └─────────────────────────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                      │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │                              MCP Server                                        │ │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │  │                         Available Tools                                 │   │ │
│  │  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                   │   │ │
│  │  │  │ create_item  │  │  get_item    │  │ list_items   │                   │   │ │
│  │  │  │ (mcp:write)  │  │ (mcp:read)   │  │ (mcp:read)   │                   │   │ │
│  │  │  └──────────────┘  └──────────────┘  └──────────────┘                   │   │ │
│  │  │  ┌──────────────┐  ┌──────────────┐                                     │   │ │
│  │  │  │ update_item  │  │ delete_item  │                                     │   │ │
│  │  │  │ (mcp:write)  │  │ (mcp:delete) │                                     │   │ │
│  │  │  └──────────────┘  └──────────────┘                                     │   │ │
│  │  └─────────────────────────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              DATA LAYER                                              │
│                                                                                      │
│  ┌──────────────────────────────┐    ┌──────────────────────────────┐               │
│  │        MongoDB               │    │          Redis               │               │
│  │    (Hot State Storage)       │    │    (Cold State Storage)      │               │
│  │                              │    │                              │               │
│  │  • Agent session state       │    │  • Archived checkpoints      │               │
│  │  • Current execution plan    │    │  • Session cache             │               │
│  │  • Task results              │    │  • Token blacklist           │               │
│  │  • User data                 │    │                              │               │
│  │  • Items collection          │    │                              │               │
│  └──────────────────────────────┘    └──────────────────────────────┘               │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                            EXTERNAL SERVICES                                         │
│                                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                    Google Cloud Platform - Vertex AI                          │   │
│  │                                                                               │   │
│  │  • Model: Gemini 2.5 Pro                                                      │   │
│  │  • Authentication: Service Account JSON                                       │   │
│  │  • Region: us-central1 (configurable)                                         │   │
│  │                                                                               │   │
│  │  AI Capabilities:                                                             │   │
│  │  ├── Plan Generation: Analyzes goals, creates structured execution plans     │   │
│  │  ├── Task Execution: Executes individual tasks with context awareness        │   │
│  │  ├── MCP Analysis: Determines which tools to use for a goal                  │   │
│  │  └── Summary Generation: Creates execution summaries                          │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. Plan Generation Flow

```
┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌──────────┐    ┌──────────┐
│  User    │───▶│  React   │───▶│   FastAPI    │───▶│ Multi-   │───▶│ Vertex   │
│  Input   │    │  UI      │    │   Backend    │    │ Agent    │    │ AI       │
│ (Goal)   │    │          │    │   (SSE)      │    │ Orch.    │    │ Gemini   │
└──────────┘    └──────────┘    └──────────────┘    └──────────┘    └──────────┘
                     │                 │                  │               │
                     │                 │                  │               │
                     │  SSE Stream     │                  │               │
                     │◀────────────────│◀─────────────────│◀──────────────│
                     │                 │                  │               │
                     │  Events:        │                  │               │
                     │  - status       │                  │               │
                     │  - thinking     │                  │               │
                     │  - plan_step    │                  │               │
                     │  - plan_complete│                  │               │
                     ▼                 ▼                  ▼               ▼
```

### 2. Plan Execution Flow

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          Plan Execution Pipeline                                  │
│                                                                                   │
│  Step 1: Research Phase (PARALLEL)                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                       │ │
│  │  │ AI Task 1    │  │ AI Task 2    │  │ AI Task 3    │   Running in parallel │ │
│  │  │ Search DB    │  │ Query APIs   │  │ Analyze Data │                       │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘                       │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                              │
│                                    ▼                                              │
│  Step 2: Analysis Phase (SEQUENTIAL)                                             │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  ┌──────────────┐    ┌──────────────┐                                       │ │
│  │  │ AI Task 1    │───▶│ AI Task 2    │   Tasks run one after another        │ │
│  │  │ Process Data │    │ Extract      │   with context from previous         │ │
│  │  └──────────────┘    └──────────────┘                                       │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                              │
│                                    ▼                                              │
│  Step 3: Execution Phase (SEQUENTIAL)                                            │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │ │
│  │  │ AI Task 1    │───▶│ AI Task 2    │───▶│ AI Task 3    │                   │ │
│  │  │ Prepare      │    │ Execute      │    │ Post-process │                   │ │
│  │  └──────────────┘    └──────────────┘    └──────────────┘                   │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                              │
│                                    ▼                                              │
│  Step 4: Data Operations Phase (SEQUENTIAL with MCP)                             │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │ │
│  │  │ Validate     │───▶│ Call MCP     │───▶│ Verify       │                   │ │
│  │  │ Data         │    │ Tools        │    │ Results      │                   │ │
│  │  └──────────────┘    └──────────────┘    └──────────────┘                   │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                              │
│                                    ▼                                              │
│  Step 5: Validation Phase (SEQUENTIAL)                                           │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │  ┌──────────────┐    ┌──────────────┐                                       │ │
│  │  │ AI Task 1    │───▶│ AI Task 2    │                                       │ │
│  │  │ Verify       │    │ Generate     │                                       │ │
│  │  │ Outputs      │    │ Summary      │                                       │ │
│  │  └──────────────┘    └──────────────┘                                       │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## Logging Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              Structured Logging                                      │
│                                                                                      │
│  Every request/response is logged with:                                              │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │  {                                                                              │ │
│  │    "timestamp": "2024-01-15T10:30:45.123Z",                                     │ │
│  │    "level": "INFO",                                                             │ │
│  │    "request_id": "abc12345",        // Unique per request                       │ │
│  │    "session_id": "xyz78901",        // Agent session ID                         │ │
│  │    "user_id": "user123",            // Authenticated user                       │ │
│  │    "agent_type": "planning",        // Which agent is active                    │ │
│  │    "phase": "research",             // Current execution phase                  │ │
│  │    "message": "AI Request to gemini-2.5-pro",                                   │ │
│  │    "data": {                        // Additional context                       │ │
│  │      "prompt_preview": "...",                                                   │ │
│  │      "goal": "..."                                                              │ │
│  │    },                                                                           │ │
│  │    "duration_ms": 1234              // For timing-related logs                  │ │
│  │  }                                                                              │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                      │
│  Log Categories:                                                                     │
│  • 📥 Request received                                                              │
│  • 📤 Response sent                                                                 │
│  • 🤖 AI request/response                                                           │
│  • 🚀 Agent started                                                                 │
│  • ✅ Agent completed                                                               │
│  • 📍 Step started                                                                  │
│  • ✓ Step completed                                                                │
│  • ⚡ Parallel execution                                                            │
│  • 📋 Sequential execution                                                          │
│  • ❌ Errors                                                                        │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Authentication & Authorization

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              RBAC System                                             │
│                                                                                      │
│  Roles:                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │  admin     │ items:* agent:* mcp:*                     │ Full access            │ │
│  │  user      │ items:read,write,delete agent:* mcp:r,w   │ Standard user         │ │
│  │  read_only │ items:read mcp:read                       │ View only             │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                      │
│  Token Flow:                                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐                       │
│  │  Login   │───▶│ Generate │───▶│  Include │───▶│ Validate │                       │
│  │ Request  │    │ JWT      │    │ in Header│    │ & Check  │                       │
│  └──────────┘    └──────────┘    └──────────┘    │ Perms    │                       │
│                                                   └──────────┘                       │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Checkpoint Storage

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         State Management                                             │
│                                                                                      │
│  Hot State (MongoDB):                      Cold State (Redis):                       │
│  ┌──────────────────────────────┐         ┌──────────────────────────────┐          │
│  │ • Active sessions            │         │ • Completed sessions          │          │
│  │ • In-progress plans          │ ──────▶ │ • Archived checkpoints        │          │
│  │ • Current execution state    │ (after  │ • Historical data             │          │
│  │ • Real-time updates          │  done)  │ • Session cache               │          │
│  └──────────────────────────────┘         └──────────────────────────────┘          │
│                                                                                      │
│  Checkpoint Structure:                                                               │
│  {                                                                                   │
│    "session_id": "uuid",                                                            │
│    "user_id": "user123",                                                            │
│    "state_type": "hot|cold",                                                        │
│    "state_data": { ... plan, tasks, results ... },                                  │
│    "created_at": "timestamp",                                                       │
│    "updated_at": "timestamp"                                                        │
│  }                                                                                   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Docker Deployment

```yaml
services:
  app:           # FastAPI Backend (Port 8000)
  mcp-server:    # MCP Server (Port 8001) - Separate container
  agent-service: # LangGraph Agent (Port 8002) - Future
  mongodb:       # Hot State Storage (Port 27017)
  redis:         # Cold State Storage (Port 6379)
  frontend:      # React UI (Port 3000)

# Environment:
# - GOOGLE_APPLICATION_CREDENTIALS: Service account JSON
# - GOOGLE_CLOUD_PROJECT: GCP project ID
# - JWT_SECRET_KEY: For token signing
# - MONGODB_URL: MongoDB connection string
# - REDIS_URL: Redis connection string
# - MCP_SERVER_URL: MCP Server URL (http://mcp-server:8001)
# - BACKEND_URL: Backend API URL (http://app:8000)
```

---

## Current Architecture (MCP-First)

The application uses a **MCP-first architecture** where the MCP Server is a separate container that communicates with the Backend API via HTTP with Bearer token authorization.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (UI)                                   │
│  React Dashboard - Goals, Plan View, Execution Monitor, Items CRUD          │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BACKEND API SERVER (:8000)                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Auth Service │  │ Items API    │  │ Users API    │  │ Reports API  │     │
│  │ (JWT/RBAC)   │  │ (CRUD)       │  │ (CRUD)       │  │ (Analytics)  │     │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘     │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    AI Agent (Multi-Agent Orchestrator)                │   │
│  │  • Receives user goals                                                │   │
│  │  • Generates plans using AI (Vertex AI Gemini)                        │   │
│  │  • Executes plans via MCP Client → MCP Server                         │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         MCP CLIENT (JSON-RPC)                         │   │
│  │  • Communicates with external MCP Server                              │   │
│  │  • Sends Bearer token for authorization                               │   │
│  │  • Methods: list_tools(), call_tool(), list_resources()               │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MCP SERVER (:8001)                                  │
│                     (Separate Container - MCP Protocol)                      │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    TRANSPORT LAYER (HTTP/SSE)                         │   │
│  │  GET  /sse      - Server-Sent Events for streaming                    │   │
│  │  POST /message  - JSON-RPC 2.0 requests                               │   │
│  │  GET  /tools    - List available tools                                │   │
│  │  GET  /health   - Health check                                        │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                      │                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    DATA LAYER (JSON-RPC 2.0)                          │   │
│  │  Methods:                                                             │   │
│  │  • initialize      - MCP lifecycle initialization                     │   │
│  │  • tools/list      - List available tools                             │   │
│  │  • tools/call      - Execute a tool                                   │   │
│  │  • resources/list  - List available resources                         │   │
│  │  • resources/read  - Read a resource                                  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                      │                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    TOOL EXECUTOR (Backend Client)                     │   │
│  │  • Receives Bearer token from MCP Client                              │   │
│  │  • Calls Backend API with Authorization header                        │   │
│  │  • NO direct database access - all via API                            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BACKEND API SERVER (:8000)                           │
│                    (MCP Server calls back to Backend)                        │
│                                                                              │
│  Tool execution flow:                                                        │
│  MCP Server → POST /items/ (with Bearer token) → Backend validates → DB     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATA LAYER                                      │
│  ┌──────────────────────────┐  ┌──────────────────────────────────────┐     │
│  │   MongoDB (Hot State)    │  │      Redis (Cold State/Cache)        │     │
│  │   - Users, Items         │  │      - Session cache                 │     │
│  │   - Active sessions      │  │      - Completed sessions            │     │
│  └──────────────────────────┘  └──────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Request Flow

```
User → Frontend → Backend API → AI Agent → MCP Client → MCP Server → Backend API → MongoDB
                                              ↑
                                         Bearer Token
                                    (passed through chain)
```

### Available MCP Tools (12 Tools)

| Tool | Description | Permission |
|------|-------------|------------|
| `create_item` | Create new item | items:write |
| `read_item` | Read item by ID | items:read |
| `update_item` | Update existing item | items:write |
| `delete_item` | Delete item | items:delete |
| `list_items` | List with pagination | items:read |
| `search_items` | Text search | items:read |
| `bulk_create` | Create multiple items | items:write |
| `bulk_delete` | Delete multiple items | items:delete |
| `get_statistics` | Database stats | items:read |
| `generate_report` | Reports | items:read |
| `get_user_profile` | Get current user | users:read |
| `update_user_profile` | Update user profile | users:write |

---

## Future: Scalable Architecture (100+ Tools)

When scaling to 100+ tools, the current approach of sending ALL tools to the AI will hit context window limits (~50K tokens just for tool schemas). The recommended solution is **MCP Tool Search**.

### The Problem

| Scenario | Tokens Used |
|----------|-------------|
| All 100 tools loaded | ~50,000 tokens ❌ |
| Tool Search → 10 tools | ~5,000 tokens ✅ |
| **Savings** | **90%** |

### Solution: MCP Tool Search (Like Claude Code)

Claude Code uses a **hybrid search approach**:

| Method | Speed | Accuracy | Use Case |
|--------|-------|----------|----------|
| **BM25** | ~1ms | ~80% | Keyword matching |
| **Embeddings** | ~300ms | ~100% | Semantic understanding |
| **Hybrid** | ~50ms | ~95% | Production (best of both) |

### How It Works

1. **Index tool metadata** (name, summary, tags) - NOT full schemas
2. **User query** → Search/rank against metadata index
3. **Load ONLY top-k tool schemas** into context
4. **Execute** with minimal context usage

### Proposed Architecture (Future)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AI AGENT SERVICE (:8002)                             │
│                     (Separate Container - LangGraph)                         │
│                                                                              │
│   User Goal ──▶ [Router] ──▶ [Tool Search] ──▶ [Planner] ──▶ [Executor]    │
│                                    │                                         │
│                           ┌────────┴────────┐                                │
│                           │   TOOL SEARCH   │                                │
│                           │                 │                                │
│                           │ 1. BM25 filter  │                                │
│                           │ 2. Embed query  │                                │
│                           │ 3. Vector rank  │                                │
│                           │ 4. Top-K tools  │                                │
│                           └─────────────────┘                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MCP SERVER (:8001)                                  │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    TOOL REGISTRY (MongoDB)                            │   │
│  │                                                                       │   │
│  │  Collection: tools                                                    │   │
│  │  {                                                                    │   │
│  │    "_id": "create_item",                                              │   │
│  │    "name": "create_item",                                             │   │
│  │    "summary": "Create new item",     // Lightweight metadata          │   │
│  │    "category": "items",                                               │   │
│  │    "tags": ["crud", "write"],                                         │   │
│  │    "permissions": ["items:write"],                                    │   │
│  │    "embedding": [0.1, 0.2, ...],     // For vector search             │   │
│  │    "schema": { ... },                // Full schema (deferred load)   │   │
│  │    "endpoint": "POST /items/"                                         │   │
│  │  }                                                                    │   │
│  │                                                                       │   │
│  │  Indexes:                                                             │   │
│  │  - Text index on (name, summary, tags) for BM25                       │   │
│  │  - Vector index on embedding for semantic search                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  New Endpoints (Future):                                                     │
│  GET  /tools/search?q=create+item    → Returns matching tool metadata       │
│  GET  /tools/{id}/schema             → Returns full schema on-demand        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation Steps (Future)

1. **Tool Registry**: MongoDB collection with text + vector indexes
2. **Hybrid Search**: Combine BM25 and embedding search with RRF ranking
3. **Deferred Loading**: Only load full schemas for selected tools
4. **Agent Service**: Separate LangGraph container with tool_search node

### LangGraph Integration (Future)

```python
from langgraph.graph import StateGraph
from langgraph.checkpoint.mongodb import MongoDBSaver

class AgentState(TypedDict):
    goal: str
    selected_tools: List[ToolMetadata]  # Lightweight!
    tool_schemas: List[ToolSchema]       # Loaded on-demand
    plan: List[PlanStep]
    results: List[Any]

async def tool_search_node(state: AgentState) -> AgentState:
    """Search for relevant tools - NOT load all 100!"""
    relevant_tools = await hybrid_search(state["goal"], limit=10)
    schemas = [await get_schema(t["_id"]) for t in relevant_tools]
    return {**state, "selected_tools": relevant_tools, "tool_schemas": schemas}

workflow = StateGraph(AgentState)
workflow.add_node("tool_search", tool_search_node)
workflow.add_node("planner", planner_node)
workflow.add_node("executor", executor_node)

checkpointer = MongoDBSaver(mongodb_client)
app = workflow.compile(checkpointer=checkpointer)
```

### References

- [Anthropic Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use)
- [Claude Tool Search with Embeddings](https://platform.claude.com/cookbook/tool-use-tool-search-with-embeddings)
- [MCP Tool Search Implementation](https://github.com/ImBIOS/tool-search-mcp)
