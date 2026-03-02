# System Architecture

This document describes the architecture of the AI Experiments MCP Demo Application — a containerized Python application demonstrating scalable multi-agent AI workflows with MCP (Model Context Protocol), LangGraph orchestration, and JWT-based RBAC.

---

## Quick Reference

| Component | Port | Technology | Purpose |
|-----------|------|------------|---------|
| Frontend | 3000 | React + Vite | User interface (Plan Mode + Chat Mode) |
| Backend | 8000 | FastAPI + LangGraph | API server, AI orchestration, checkpointing |
| MCP Server | 8001 | **FastMCP** + FastAPI | Tool execution via MCP protocol (dual transport) |
| MongoDB | 27017 | MongoDB 7.0 | Permanent state storage + LangGraph checkpoints |
| Redis | 6379 | Redis 7 Alpine | Hot state cache, token blacklist |

---

## System Diagram

```
┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐
│   Frontend       │  SSE   │   Backend        │  HTTP  │   MCP Server     │
│   (React+Vite)   │──────▶ │   (FastAPI)      │──────▶ │   (FastMCP)      │
│   :3000          │        │   :8000          │        │   :8001          │
│                  │        │                  │        │                  │
│  ┌────────────┐  │        │  ┌────────────┐  │        │  ┌────────────┐  │
│  │ Plan Mode  │  │        │  │ LangGraph  │  │        │  │ @mcp.tool  │  │
│  │ Chat Mode  │  │        │  │ ReAct Agent│  │        │  │ CRUD Tools │  │
│  └────────────┘  │        │  └────────────┘  │        │  └────────────┘  │
└──────────────────┘        └────────┬─────────┘        └────────┬─────────┘
                                     │                           │
                              ┌──────┴──────┐                    │
                              ▼             ▼                    │
                        ┌──────────┐  ┌─────────┐               │
                        │ MongoDB  │  │  Redis  │               │
                        │  :27017  │  │  :6379  │               │
                        │          │  │         │               │
                        │ • Items  │  │ • Token │               │
                        │ • Users  │  │   Black │               │
                        │ • Check- │  │   list  │               │
                        │   points │  │ • Hot   │               │
                        │   (cold) │  │   Cache │               │
                        └──────────┘  └─────────┘               │
                              ▲                                  │
                              └──────────────────────────────────┘
                              MCP Server calls Backend API
                              with user's JWT for authorization
```

### Key Design Principle

The MCP Server **never** accesses the database directly. All data access goes through the Backend API with the user's JWT token — ensuring authorization is enforced at every layer.

---

## Two AI Modes

### Plan Mode (Multi-Step with Human Approval)

Uses **LangGraph StateGraph** with `interrupt()` for human-in-the-loop approval.

```
User Goal → AI Planner → Plan Review → Human Approval → Parallel Execution → Summary
```

### Chat Mode (Direct ReAct Agent)

Uses **`create_react_agent`** from `langgraph-prebuilt`. AI autonomously calls tools.

```
User Message → ReAct Agent → Tool Calls → Final Response
```

---

## LangGraph State Machine (Plan Mode)

```
START → planner_node → approval_node (interrupt)
                            ↓
                       check_approval()
                      ✓ approved    ✗ rejected
                            ↓              ↓
                    executor_dispatch    summary → END
                            ↓
                    create_task_sends() → Send() per task
                            ↓
                    task_executor_node (parallel)
                            ↓
                    step_aggregator_node
                            ↓
                    should_continue?
                    ├── more steps → executor_dispatch
                    └── done → summary → END
```

**Checkpointing**: State saved to MongoDB after every node via `MongoDBSaver`. Sessions can be stopped, resumed, or replanned mid-execution.

---

## RBAC Roles

| Role | Permissions | Can Do |
|------|-------------|--------|
| `admin` | `users:*`, `items:*`, `agent:*`, `mcp:*` | Everything |
| `user` | `items:read/write/delete`, `agent:execute`, `mcp:read/write` | CRUD items, run agent |
| `read_only` | `items:read`, `mcp:read` | View only — write operations return 403 |

---

## MCP Server Dual Transport

| Transport | Endpoint | Used By | Auth |
|-----------|----------|---------|------|
| JSON-RPC 2.0 | `POST /message` | Plan Mode (via `MCPClientWrapper`) | `auth_token` parameter |
| Streamable HTTP | `POST /mcp` | Chat Mode (via `MultiServerMCPClient`) | `Authorization` header |

Both transports call the same `@mcp.tool` functions. Tools use dual auth:
```python
token = _extract_token_from_context(ctx) or auth_token
```

---

## Key Files

| File | Purpose |
|------|---------|
| `app/agent/graph.py` | LangGraph StateGraph orchestrator |
| `app/agent/react_agent.py` | ReAct agent with `create_react_agent` |
| `app/agent/state.py` | TypedDict state schema with reducers |
| `app/agent/nodes.py` | Node implementations (planner, approval, executor, summary) |
| `app/api/streaming.py` | SSE endpoints for Plan + Chat modes |
| `app/auth/authorization.py` | RBAC: roles, permissions, JWT, blacklist |
| `app/mcp/client.py` | MCP client (langchain-mcp-adapters + JSON-RPC fallback) |
| `mcp-server/src/server.py` | FastMCP `@mcp.tool` definitions |
| `mcp-server/src/app.py` | FastAPI wrapper + native MCP endpoint |
| `frontend/src/components/AgentPanel.jsx` | AI agent UI (Plan/Chat toggle) |

---

## Available MCP Tools (6)

| Tool | Action | Required Permission |
|------|--------|-------------------|
| `create_item` | Create item | `items:write` |
| `read_item` | Get item by ID | `items:read` |
| `update_item` | Update item | `items:write` |
| `delete_item` | Delete item | `items:delete` |
| `list_items` | List all items | `items:read` |
| `search_items` | Text search | `items:read` |

---

## Docker Compose Services

```yaml
services:
  app:          # Backend (FastAPI + LangGraph + AI)  → :8000
  mcp-server:   # MCP Server (FastMCP + FastAPI)      → :8001
  mongodb:      # MongoDB 7.0 (permanent storage)     → :27017
  redis:        # Redis 7 Alpine (cache + blacklist)   → :6379
```

All services communicate via `app-network` bridge. MCP Server calls Backend API at `http://app:8000`. Backend calls MCP Server at `http://mcp-server:8001`.
