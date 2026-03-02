# AI Experiments - Developer Guide

This guide provides an end-to-end walkthrough of the codebase, explaining how each component works and how they interact.

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture Summary](#architecture-summary)
3. [Component Deep Dive](#component-deep-dive)
4. [Request Flow Examples](#request-flow-examples)
5. [RBAC System](#rbac-system)
6. [AI Agent System](#ai-agent-system)
7. [MCP Protocol](#mcp-protocol)
8. [Debugging & Logging](#debugging--logging)
9. [Common Tasks](#common-tasks)

---

## Project Overview

This is a containerized Python application demonstrating:
- **MCP Server** (Model Context Protocol) - Standardized tool interface for AI
- **LangGraph-style Multi-Agent System** - Planning and execution agents
- **JWT-based RBAC** - Role-based access control
- **Hot/Cold State Storage** - MongoDB (hot) + Redis (cold)

### Tech Stack

| Component | Technology |
|-----------|------------|
| Backend API | FastAPI (Python 3.11) |
| Frontend | React + Vite + TailwindCSS |
| MCP Server | Python + MCP SDK |
| AI | Google Vertex AI (Gemini) |
| Database | MongoDB |
| Cache | Redis |
| Container | Docker Compose |

---

## Architecture Summary

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend  │────▶│   Backend   │────▶│ MCP Server  │
│   (React)   │     │  (FastAPI)  │     │  (Python)   │
│   :3000     │     │   :8000     │     │   :8001     │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                   │
                    ┌──────┴──────┐            │
                    ▼             ▼            │
              ┌──────────┐  ┌─────────┐       │
              │ MongoDB  │  │  Redis  │       │
              │  :27017  │  │  :6379  │       │
              └──────────┘  └─────────┘       │
                    ▲                         │
                    └─────────────────────────┘
                    (MCP Server calls Backend API)
```

### Key Design Principle: MCP Server Has No Direct DB Access

The MCP Server **never** accesses the database directly. Instead:
1. MCP Server receives tool call with Bearer token
2. MCP Server calls Backend API with that token
3. Backend API validates token and executes operation
4. Result flows back through the chain

This ensures **all authorization happens at the Backend API level**.

---

## Component Deep Dive

### 1. Frontend (`/frontend`)

```
frontend/
├── src/
│   ├── components/
│   │   ├── Login.jsx         # Auth + quick login buttons
│   │   ├── Dashboard.jsx     # Main layout with tabs
│   │   ├── ItemsPanel.jsx    # CRUD operations UI
│   │   ├── AgentPanel.jsx    # AI agent interface
│   │   └── MCPPanel.jsx      # MCP server status
│   ├── App.jsx               # Root component
│   └── main.jsx              # Entry point
└── package.json
```

**Key Files:**

- **Login.jsx**: Handles authentication with quick login buttons for demo users
- **AgentPanel.jsx**: AI agent interface with SSE streaming for real-time updates
- **ItemsPanel.jsx**: CRUD interface with permission-based button visibility

### 2. Backend API (`/app`)

```
app/
├── main.py                   # FastAPI app, middleware, startup
├── api/
│   ├── auth_routes.py        # /auth/* endpoints
│   ├── items_routes.py       # /items/* CRUD endpoints
│   ├── agent_routes.py       # /agent/* AI endpoints
│   └── mcp_routes.py         # /mcp/* MCP proxy endpoints
├── agent/
│   ├── ai_service.py         # Vertex AI integration
│   └── multi_agent.py        # Plan generation & execution
├── auth/
│   ├── jwt_handler.py        # JWT encode/decode
│   ├── authorization.py      # RBAC permission checks
│   └── dependencies.py       # FastAPI auth dependencies
├── crud/
│   └── operations.py         # MongoDB CRUD operations
├── models/
│   ├── user.py               # User model with roles
│   └── item.py               # Item model
├── mcp/
│   └── client.py             # MCP Server HTTP client
├── checkpoints/
│   └── manager.py            # Hot/cold state management
└── config/
    ├── settings.py           # Environment config
    └── logging_config.py     # Structured logging
```

**Key Files Explained:**

#### `app/main.py`
- Creates FastAPI app with CORS
- Request logging middleware
- Startup: connects MongoDB, Redis, initializes AI service

#### `app/agent/ai_service.py`
- **`generate_plan()`**: Sends goal to Vertex AI, returns structured plan
- **`execute_task()`**: Executes a task, optionally calling MCP tools
- Uses `[AIFLOW]` prefix for grepable logging

#### `app/agent/multi_agent.py`
- **`MultiAgentOrchestrator`**: Manages agent sessions
- **`generate_plan_streaming()`**: Streams plan generation via SSE
- **`execute_plan_streaming()`**: Executes plan steps with streaming updates
- Handles parallel vs sequential execution modes
- Stops execution on authorization failures

#### `app/auth/authorization.py`
- Defines role permissions:
  ```python
  ROLE_PERMISSIONS = {
      UserRole.ADMIN: ["users:*", "items:*", "agent:*", "mcp:*"],
      UserRole.USER: ["items:read", "items:write", "items:delete", "agent:execute", "mcp:*"],
      UserRole.READ_ONLY: ["items:read", "mcp:read"]
  }
  ```

### 3. MCP Server (`/mcp-server`)

```
mcp-server/
├── src/
│   ├── main.py               # FastAPI app with MCP endpoints
│   ├── tools/
│   │   ├── registry.py       # Tool registration
│   │   └── item_tools.py     # Item CRUD tool implementations
│   └── protocol/
│       └── lifecycle.py      # MCP initialize/shutdown
└── requirements.txt
```

**Key Files:**

#### `mcp-server/src/main.py`
- HTTP transport for MCP (POST /message, GET /sse)
- JSON-RPC 2.0 message routing
- Tool execution with Bearer token passthrough

#### `mcp-server/src/tools/item_tools.py`
- Implements MCP tools that call Backend API:
  ```python
  async def create_item(name, description, data, token):
      async with httpx.AsyncClient() as client:
          response = await client.post(
              f"{BACKEND_URL}/items/",
              headers={"Authorization": f"Bearer {token}"},
              json={"name": name, "description": description, "data": data}
          )
          return response.json()
  ```

---

## Request Flow Examples

### Example 1: User Login

```
1. Frontend: POST /auth/login {email, password}
2. Backend: Verify credentials in MongoDB
3. Backend: Generate JWT with user_id, role, permissions
4. Frontend: Store token, redirect to dashboard
```

### Example 2: Create Item via UI

```
1. Frontend: POST /items/ {name, description} + Bearer token
2. Backend: Validate JWT, check items:write permission
3. Backend: Insert into MongoDB
4. Backend: Return created item
5. Frontend: Update UI
```

### Example 3: AI Agent Creates Item

```
1. Frontend: POST /agent/sessions {goal: "create item X"}
2. Backend: Create session, start SSE stream
3. Backend (AI Service): Send goal to Vertex AI
4. Vertex AI: Return structured plan with steps
5. Backend: Stream plan steps to frontend
6. Frontend: User clicks "Execute"
7. Backend: Execute each step:
   a. For MCP tool steps:
      - Backend → MCP Server: POST /message {tool: create_item, token}
      - MCP Server → Backend: POST /items/ + Bearer token
      - Backend: Validate token, execute, return result
      - MCP Server → Backend: Return tool result
   b. Stream results to frontend
8. Frontend: Display results
```

### Example 4: Authorization Failure (Viewer Creates Item)

```
1. Viewer logs in (role: read_only, permissions: [items:read, mcp:read])
2. Viewer: "create item X" via Agent
3. AI generates plan with create_item step
4. Execution starts:
   - Backend → MCP Server: POST /message {tool: create_item, token}
   - MCP Server → Backend: POST /items/ + Bearer token
   - Backend: Check permission → FAIL (needs items:write)
   - Backend: Return 403 Forbidden
   - MCP Server → Backend: Return "Authorization error: Forbidden"
5. Backend detects auth error in result
6. Backend: Stop execution, emit "execution_stopped" event
7. Frontend: Display "Authorization denied" message
```

---

## RBAC System

### Roles and Permissions

| Role | Permissions | Can Do |
|------|-------------|--------|
| `admin` | `users:*`, `items:*`, `agent:*`, `mcp:*` | Everything |
| `user` | `items:read/write/delete`, `agent:execute`, `mcp:*` | CRUD items, run agent |
| `read_only` | `items:read`, `mcp:read` | View items, run agent (read-only operations) |

### Demo Users

| Username | Password | Role |
|----------|----------|------|
| admin_demo@test.com | admin123 | admin |
| user_demo@test.com | user123 | user |
| viewer_demo@test.com | viewer123 | read_only |

### Permission Check Flow

```python
# In auth/dependencies.py
async def require_permission(permission: str):
    def dependency(current_user: User = Depends(get_current_user)):
        if not has_permission(current_user, permission):
            raise HTTPException(403, "Insufficient permissions")
        return current_user
    return Depends(dependency)

# Usage in routes
@router.post("/")
async def create_item(
    item: ItemCreate,
    user: User = Depends(require_permission("items:write"))
):
    ...
```

### Key Design: Auth at Tool Execution, Not Planning

**Important**: The AI does NOT know about user permissions when planning. This is intentional:

1. **Planning Phase**: AI creates plan for any goal freely
2. **Execution Phase**: Each MCP tool call includes the user's token
3. **Authorization**: Backend validates token on each API call
4. **Failure Handling**: If auth fails, execution stops with clear error

This ensures the AI can plan any operation, and users see exactly which step failed due to permissions.

---

## AI Agent System

### Planning Flow

```
User Goal → AI Service → Vertex AI → Structured Plan → User Review → Execute
```

### Plan Structure

```json
{
  "analysis": "Brief analysis of the goal",
  "steps": [
    {
      "phase": "execution",
      "description": "Create the item",
      "agent_type": "execution",
      "execution_mode": "sequential",
      "sub_tasks": [
        {
          "name": "Create Item",
          "description": "Create item with given data",
          "tool": "create_item",
          "tool_params": {"name": "X", "description": "Y"}
        }
      ]
    }
  ]
}
```

### Execution Modes

- **parallel**: Tasks run concurrently (e.g., multiple searches)
- **sequential**: Tasks run one after another (e.g., create then verify)

### Agent Types

- **research**: Gathers information (list, search, read)
- **execution**: Performs actions (create, update, delete)
- **validation**: Verifies results

---

## MCP Protocol

### What is MCP?

Model Context Protocol (MCP) is a standard for AI models to interact with external tools. Key concepts:

- **Tools**: Functions the AI can call (e.g., create_item, search_items)
- **Resources**: Data the AI can access (e.g., database contents)
- **Transport**: HTTP + SSE for communication

### MCP Message Format (JSON-RPC 2.0)

```json
// Request
{
  "jsonrpc": "2.0",
  "id": "uuid",
  "method": "tools/call",
  "params": {
    "name": "create_item",
    "arguments": {"name": "X", "description": "Y"}
  }
}

// Response
{
  "jsonrpc": "2.0",
  "id": "uuid",
  "result": {
    "content": [{"type": "text", "text": "{\"id\": \"123\", ...}"}]
  }
}
```

### Available Tools (12)

| Tool | Action | Permission |
|------|--------|------------|
| create_item | Create item | items:write |
| read_item | Get item by ID | items:read |
| update_item | Update item | items:write |
| delete_item | Delete item | items:delete |
| list_items | List all items | items:read |
| search_items | Text search | items:read |
| bulk_create | Create multiple | items:write |
| bulk_delete | Delete multiple | items:delete |
| get_statistics | DB stats | items:read |
| generate_report | Reports | items:read |
| get_user_profile | Current user | users:read |
| update_user_profile | Update profile | users:write |

---

## Debugging & Logging

### Log Prefixes

Use these prefixes to grep logs:

```bash
# AI prompts and responses
docker logs ai-experiments-app-1 | grep "\[AIFLOW\]"

# Specific log types
[AIFLOW] AI Prompt: ...       # Full prompt sent to Vertex AI
[AIFLOW] AI Response: ...     # Full response from AI
[AIFLOW] MCP Tool Called: ... # Tool name and params
[AIFLOW] MCP Tool Result: ... # Tool execution result
```

### Request Tracing

Every request gets a unique `X-Request-ID` header:

```bash
# Find specific request
docker logs ai-experiments-app-1 | grep "req:abc123"
```

### Container Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f app
docker-compose logs -f mcp-server
docker-compose logs -f mongodb

# Last N lines
docker-compose logs --tail 100 app
```

### Common Debug Commands

```bash
# Check service health
curl http://localhost:8000/health
curl http://localhost:8001/health

# List MCP tools
curl http://localhost:8001/tools

# Test auth
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin_demo@test.com","password":"admin123"}'
```

---

## Common Tasks

### Adding a New MCP Tool

1. **Define tool in MCP Server** (`mcp-server/src/tools/item_tools.py`):
   ```python
   async def my_new_tool(param1: str, token: str) -> dict:
       async with httpx.AsyncClient() as client:
           response = await client.get(
               f"{BACKEND_URL}/my-endpoint",
               headers={"Authorization": f"Bearer {token}"}
           )
           return response.json()
   ```

2. **Register tool** (`mcp-server/src/tools/registry.py`):
   ```python
   TOOLS = {
       "my_new_tool": {
           "description": "Does something useful",
           "parameters": {"param1": {"type": "string", "required": True}},
           "handler": my_new_tool,
           "permission": "items:read"
       }
   }
   ```

3. **Add Backend endpoint** if needed (`app/api/items_routes.py`)

4. **Update tool description** (`app/agent/tools.py`)

### Adding a New Role

1. **Define role** (`app/models/user.py`):
   ```python
   class UserRole(str, Enum):
       ADMIN = "admin"
       USER = "user"
       READ_ONLY = "read_only"
       NEW_ROLE = "new_role"  # Add here
   ```

2. **Set permissions** (`app/auth/authorization.py`):
   ```python
   ROLE_PERMISSIONS = {
       ...
       UserRole.NEW_ROLE: ["items:read", "special:permission"]
   }
   ```

### Restarting Services

```bash
# Rebuild and restart single service
docker-compose build app && docker-compose up -d app

# Restart all services
docker-compose down && docker-compose up -d

# Full rebuild (no cache)
docker-compose build --no-cache && docker-compose up -d
```

### Running Tests

```bash
# Backend tests
docker-compose exec app pytest

# MCP Server tests
docker-compose exec mcp-server pytest

# Frontend tests
cd frontend && npm test
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MONGODB_URL` | MongoDB connection string | mongodb://mongodb:27017 |
| `REDIS_URL` | Redis connection string | redis://redis:6379 |
| `JWT_SECRET` | Secret for JWT signing | (required) |
| `GOOGLE_CLOUD_PROJECT` | GCP project for Vertex AI | (required) |
| `VERTEXAI_LOCATION` | Vertex AI region | us-central1 |
| `VERTEXAI_MODEL` | Gemini model name | gemini-2.0-flash |

---

## Troubleshooting

### "AI service initialization failed"

- Check Vertex AI credentials in `credentials/` folder
- Verify `GOOGLE_APPLICATION_CREDENTIALS` env var
- Check GCP project has Vertex AI API enabled

### "Authorization error: Forbidden"

- User lacks required permission for operation
- Check user's role and permissions
- Use admin account for write operations

### "MCP Server connection failed"

- Ensure MCP Server container is running: `docker-compose ps`
- Check MCP Server logs: `docker-compose logs mcp-server`
- Verify network connectivity between containers

### "Template syntax in tool params"

- AI used `{{steps[x].output}}` syntax (not supported)
- Results are passed via `previous_results` context
- This is handled automatically by the system

---

## References

- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Vertex AI Gemini](https://cloud.google.com/vertex-ai/docs/generative-ai/model-reference/gemini)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
