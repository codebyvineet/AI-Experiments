# AI Experiments — Developer Guide

A comprehensive guide for understanding every part of this codebase: how LangGraph orchestrates multi-agent workflows, how MongoDB/Redis checkpointing works, how MCP tools are called in Plan Mode vs Chat Mode, and how JWT-based RBAC authorization flows through every layer.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Getting Started](#2-getting-started)
3. [Directory Structure](#3-directory-structure)
4. [Authorization & RBAC Deep Dive](#4-authorization--rbac-deep-dive)
5. [LangGraph Orchestration (Plan Mode)](#5-langgraph-orchestration-plan-mode)
6. [ReAct Agent (Chat Mode)](#6-react-agent-chat-mode)
7. [MongoDB & Redis Checkpointing](#7-mongodb--redis-checkpointing)
8. [MCP Server & Tool Calling](#8-mcp-server--tool-calling)
9. [SSE Streaming Endpoints](#9-sse-streaming-endpoints)
10. [Frontend UI](#10-frontend-ui)
11. [End-to-End Request Flows](#11-end-to-end-request-flows)
12. [Debugging & Logging](#12-debugging--logging)
13. [Common Tasks](#13-common-tasks)
14. [Environment Variables](#14-environment-variables)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. Project Overview

This is a **containerized Python application** demonstrating:

- **MCP Server** (Model Context Protocol) — standardized tool interface for AI agents
- **LangGraph** — multi-agent orchestration with human-in-the-loop approval
- **ReAct Agent** — direct AI-to-tool calling using `create_react_agent`
- **JWT-based RBAC** — role-based access control at every API layer
- **Hot/Cold Checkpointing** — MongoDB (permanent) + Redis (cache/blacklist)

### Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Backend API | FastAPI | Python 3.11 |
| AI Orchestration | LangGraph | 1.0.10 |
| ReAct Agent | langgraph-prebuilt | 1.0.8 |
| MCP Tools | FastMCP | 3.0.2 |
| MCP Client | langchain-mcp-adapters | 0.2.1 |
| AI Model | Google Vertex AI (Gemini) | gemini-2.5-pro |
| Database | MongoDB | 7.0 |
| Cache | Redis | 7 Alpine |
| Frontend | React + Vite | Latest |
| Container | Docker Compose | 3.8 |

---

## 2. Getting Started

### Prerequisites

- Docker & Docker Compose
- Google Cloud service account with Vertex AI API enabled
- Place `service-account.json` in `credentials/` folder

### Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env: set JWT_SECRET_KEY, GOOGLE_CLOUD_PROJECT

# 2. Start all services
docker compose up -d

# 3. Start frontend dev server
cd frontend && npm install && npm run dev

# 4. Open http://localhost:5173 (or :3000 in production)
```

### Demo Users (auto-created)

| Username | Password | Role |
|----------|----------|------|
| `admin_demo@test.com` | `admin123` | admin |
| `user_demo@test.com` | `user123` | user |
| `viewer_demo@test.com` | `viewer123` | read_only |

---

## 3. Directory Structure

```
AI-Experiments/
├── app/                              # Backend (FastAPI + LangGraph)
│   ├── main.py                       # FastAPI app, middleware, startup
│   ├── agent/                        # AI Agent logic
│   │   ├── graph.py                  # LangGraph StateGraph orchestrator
│   │   ├── react_agent.py            # ReAct chat agent (Chat Mode)
│   │   ├── state.py                  # TypedDict state schema
│   │   ├── nodes.py                  # LangGraph node implementations
│   │   ├── ai_service.py             # Vertex AI service (plan generation)
│   │   └── checkpointer.py           # Checkpoint initialization helpers
│   ├── api/                          # HTTP Endpoints
│   │   ├── streaming.py              # SSE endpoints (chat + plan)
│   │   ├── auth_routes.py            # /auth/* (login, register, logout)
│   │   ├── items_routes.py           # /items/* (CRUD)
│   │   ├── agent_routes.py           # /agent/* (legacy)
│   │   └── mcp_routes.py             # /mcp/* (tool discovery)
│   ├── auth/                         # Authentication & Authorization
│   │   └── authorization.py          # JWT, RBAC, permissions, blacklist
│   ├── mcp/                          # MCP Client
│   │   └── client.py                 # MCPClientWrapper (dual transport)
│   ├── crud/                         # Database operations
│   │   └── operations.py             # MongoDB CRUD
│   ├── models/                       # Pydantic models
│   │   └── schemas.py                # User, Item, TokenData
│   ├── checkpoints/                  # State storage
│   │   ├── mongodb_store.py          # MongoDB checkpoint helpers
│   │   └── redis_store.py            # Redis cache + token blacklist
│   └── config/                       # Configuration
│       ├── settings.py               # Pydantic Settings (env vars)
│       └── logging_config.py         # Structured logging
├── mcp-server/                       # MCP Server (FastMCP)
│   ├── src/
│   │   ├── server.py                 # @mcp.tool definitions (6 tools)
│   │   └── app.py                    # FastAPI wrapper + native MCP endpoint
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                         # React UI
│   └── src/
│       ├── components/
│       │   ├── AgentPanel.jsx        # Plan Mode + Chat Mode UI
│       │   ├── Dashboard.jsx         # System status
│       │   ├── ItemsPanel.jsx        # CRUD interface
│       │   ├── Login.jsx             # Authentication
│       │   └── McpPanel.jsx          # MCP server status
│       ├── api.js                    # API client (fetch + SSE)
│       └── App.jsx                   # Root component
├── docker-compose.yml                # All 4 services
├── Dockerfile                        # Backend image
├── requirements.txt                  # Python dependencies
├── ARCHITECTURE.md                   # System architecture overview
└── HELP.md                           # This file
```

---

## 4. Authorization & RBAC Deep Dive

Authorization happens in `app/auth/authorization.py`. Every API request is validated through JWT tokens with embedded permissions.

### 4.1 Role Definitions

```python
# app/auth/authorization.py

ROLE_PERMISSIONS: Dict[UserRole, List[str]] = {
    UserRole.ADMIN: [
        "users:read", "users:write", "users:delete",
        "items:read", "items:write", "items:delete",
        "agent:execute", "agent:admin",
        "mcp:read", "mcp:write", "mcp:admin"
    ],
    UserRole.USER: [
        "items:read", "items:write", "items:delete",
        "agent:execute",
        "mcp:read", "mcp:write"
    ],
    UserRole.READ_ONLY: [
        "items:read",
        "mcp:read"
    ]
}
```

### 4.2 JWT Token Creation

When a user logs in, a JWT token is created with their permissions embedded:

```python
# app/auth/authorization.py

def create_access_token(
    user_id: str,
    username: str,
    role: UserRole,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token with embedded permissions."""
    permissions = ROLE_PERMISSIONS.get(role, [])

    to_encode = {
        "sub": user_id,           # User's MongoDB ObjectId
        "username": username,
        "role": role.value,        # "admin", "user", or "read_only"
        "permissions": permissions  # ["items:read", "items:write", ...]
    }

    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    to_encode["exp"] = expire
    to_encode["iat"] = datetime.now(timezone.utc)

    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm="HS256")
```

**Example JWT payload for a `user` role:**
```json
{
  "sub": "69a46f15535a84ac03d133b1",
  "username": "testuser",
  "role": "user",
  "permissions": ["items:read", "items:write", "items:delete", "agent:execute", "mcp:read", "mcp:write"],
  "exp": 1709406590,
  "iat": 1709404790
}
```

### 4.3 Permission Checking (FastAPI Dependency)

Every protected endpoint uses `require_permission()` as a FastAPI dependency:

```python
# app/auth/authorization.py

def require_permission(permission: str):
    """Returns a FastAPI dependency that checks if user has the required permission."""
    async def permission_checker(
        current_user: TokenData = Depends(get_current_user)
    ) -> TokenData:
        if permission not in (current_user.permissions or []):
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: requires '{permission}'"
            )
        return current_user
    return permission_checker
```

**Usage in route handlers:**
```python
# app/api/items_routes.py

@router.post("/", response_model=Item)
async def create_item(
    item_data: ItemCreate,
    current_user: TokenData = Depends(require_permission("items:write"))
):
    """Only users with 'items:write' permission can create items."""
    return await operations.create_item(item_data, current_user.user_id)


@router.get("/", response_model=List[Item])
async def list_items(
    current_user: TokenData = Depends(require_permission("items:read"))
):
    """Any authenticated user with 'items:read' can list items."""
    return await operations.list_items()
```

### 4.4 Token Validation Flow

```python
# app/auth/authorization.py

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> TokenData:
    """FastAPI dependency: validate JWT and check blacklist."""
    token = credentials.credentials

    # Step 1: Check if token was revoked (stored in Redis)
    if await redis_checkpoint.is_token_blacklisted(token):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    # Step 2: Decode and validate JWT
    return decode_token(token)  # Returns TokenData with user_id, role, permissions
```

### 4.5 MCP Token Generation

When the backend calls MCP tools, it creates a short-lived token for the MCP server:

```python
# app/auth/authorization.py

async def create_mcp_token(user: TokenData, expires_minutes: int = 60) -> str:
    """Create a short-lived token specifically for MCP server calls."""
    return create_access_token(
        user_id=user.user_id,
        username=user.username,
        role=user.role,
        expires_delta=timedelta(minutes=expires_minutes)
    )
```

### 4.6 Token Blacklist (Redis)

When a user logs out, their token is added to a Redis blacklist:

```python
# Logout adds token to blacklist
await redis_checkpoint.blacklist_token(token, ttl_seconds=3600)

# Every request checks blacklist
is_blacklisted = await redis_checkpoint.is_token_blacklisted(token)
```

### 4.7 Complete Auth Flow Diagram

```
1. User logs in → POST /auth/login {username, password}
2. Backend verifies credentials in MongoDB
3. Backend creates JWT: {sub, username, role, permissions, exp, iat}
4. Frontend stores token in localStorage
5. Every request: Authorization: Bearer <token>
6. Backend dependency chain:
   get_current_user() → check Redis blacklist → decode JWT → TokenData
   require_permission("items:write") → check TokenData.permissions
7. If permission missing → 403 Forbidden
8. If token expired → 401 Unauthorized
9. Logout → token added to Redis blacklist → subsequent requests rejected
```

---

## 5. LangGraph Orchestration (Plan Mode)

Plan Mode uses a **LangGraph StateGraph** to orchestrate multi-step AI workflows with human approval. This is the core of the application.

### 5.1 State Schema

All state is defined as a TypedDict with reducers for parallel execution:

```python
# app/agent/state.py

class AgentState(TypedDict, total=False):
    # Session metadata
    session_id: str
    user_id: str
    token: str                                          # JWT for MCP authorization

    # Goal and planning
    goal: str
    plan: List[PlanStep]
    current_step: int

    # Execution state — reducers accumulate values from parallel branches
    results: Annotated[List[TaskResult], add]            # add = operator.add (list concat)
    messages: Annotated[List[Dict[str, Any]], add]

    # Status tracking
    status: Literal["initialized", "planning", "awaiting_approval",
                    "executing", "completed", "failed"]
    approved: bool
    error: Optional[str]
    summary: Optional[Dict[str, Any]]
```

**Why `Annotated[..., add]`?** When parallel tasks run via `Send()`, each task returns its own `results` list. LangGraph uses the `add` reducer to concatenate all results into one list — this is how parallel execution works without custom merge logic.

### 5.2 Plan Step Structure

```python
# app/agent/state.py

class PlanStep(TypedDict, total=False):
    step_id: str
    phase: Literal["research", "analysis", "execution", "data_operations", "validation"]
    description: str
    agent_type: Literal["research", "execution", "validation"]
    execution_mode: Literal["parallel", "sequential"]     # How sub_tasks run
    sub_tasks: List[Dict[str, Any]]                        # Individual tasks
    reasoning: str
    mcp_tools_used: List[str]                              # e.g., ["create_item"]
    status: Literal["pending", "running", "completed", "failed", "authorization_failed"]
    result: Optional[Dict[str, Any]]
```

**Example plan generated by AI:**
```json
{
  "steps": [
    {
      "step_id": "step-0",
      "phase": "data_operations",
      "description": "Create a new item for Smriti",
      "execution_mode": "parallel",
      "sub_tasks": [
        {
          "name": "createSmritiItem",
          "tool": "create_item",
          "tool_params": {
            "name": "Smriti",
            "description": "Engineer",
            "data": {"country": "US", "salary": 1000, "currency": "USD"}
          }
        }
      ]
    }
  ]
}
```

### 5.3 Graph Construction

The graph is built in `app/agent/graph.py`:

```python
# app/agent/graph.py — LangGraphOrchestrator._build_graph()

builder = StateGraph(AgentState)

# Add nodes
builder.add_node("planner", planner_node)           # AI generates plan
builder.add_node("approval", approval_node)          # Human-in-the-loop
builder.add_node("executor_dispatch", executor_dispatch)  # Fan-out
builder.add_node("task_executor", task_executor_node)     # Execute single task
builder.add_node("aggregator", step_aggregator_node)      # Combine results
builder.add_node("summary", summary_node)            # Final summary

# Edges
builder.add_edge(START, "planner")
builder.add_edge("planner", "approval")

# After approval: execute if approved, skip to summary if rejected
builder.add_conditional_edges(
    "approval",
    check_approval,
    {"executor": "executor_dispatch", "summary": "summary"}
)

# Fan-out: create Send() objects for parallel task execution
builder.add_conditional_edges(
    "executor_dispatch",
    create_task_sends  # Returns List[Send] — one per sub_task
)

# After tasks complete, aggregate and decide: more steps or done?
builder.add_edge("task_executor", "aggregator")
builder.add_conditional_edges(
    "aggregator",
    should_continue,
    {"executor": "executor_dispatch", "summary": "summary"}
)

builder.add_edge("summary", END)

# Compile with checkpointer and interrupt before approval
graph = builder.compile(
    checkpointer=self._checkpointer,       # MongoDBSaver
    interrupt_before=["approval"]           # Pause for human approval
)
```

### 5.4 Node Implementations

#### Planner Node — AI generates the plan

```python
# app/agent/nodes.py

async def planner_node(state: AgentState) -> Dict[str, Any]:
    """Generate an execution plan using AI. Does NOT check permissions."""
    from app.agent.ai_service import ai_service

    plan_steps = []
    async for event in ai_service.generate_plan(
        goal=state["goal"],
        session_id=state["session_id"],
        context={"user_id": state["user_id"]},
        user_permissions=[]  # AI plans freely — auth checked at execution
    ):
        if event["type"] == "plan_step":
            step = event["step"]
            step["step_id"] = f"step-{len(plan_steps)}"
            step["status"] = "pending"
            plan_steps.append(step)

    return {
        "plan": plan_steps,
        "status": "awaiting_approval"
    }
```

#### Approval Node — Human-in-the-loop with `interrupt()`

```python
# app/agent/nodes.py

def approval_node(state: AgentState) -> Dict[str, Any]:
    """Pause execution and wait for human approval."""
    # interrupt() PAUSES the graph — state is saved to MongoDB
    # Execution resumes when user sends approval via /execute endpoint
    approval_response = interrupt({
        "type": "plan_approval",
        "plan": state.get("plan", []),
        "message": "Please review and approve the execution plan",
        "session_id": state["session_id"]
    })

    approved = approval_response.get("approved", False)

    return {
        "approved": approved,
        "status": "executing" if approved else "failed"
    }
```

**How `interrupt()` works:**
1. Graph execution reaches `approval_node`
2. `interrupt()` saves state to MongoDB checkpoint
3. Graph execution stops — SSE stream sends `plan_complete` event
4. Frontend shows the plan for user review
5. User clicks "Execute" → `POST /stream/sessions/{id}/execute`
6. Backend resumes graph with `graph.astream(Command(resume={"approved": True}))`
7. `interrupt()` returns `{"approved": True}` and execution continues

#### Executor Dispatch — Parallel task fan-out with `Send()`

```python
# app/agent/nodes.py

def create_task_sends(state: AgentState) -> List[Send]:
    """Create Send() objects for parallel task execution."""
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)
    step = plan[current_step]
    sub_tasks = step.get("sub_tasks", [])

    # Collect results from previous steps for context passing
    previous_results = [
        {"task_name": r.get("task_name"), "status": r.get("status"), "result": r.get("result")}
        for r in state.get("results", [])
    ]

    # Each Send() spawns a parallel task_executor_node
    return [
        Send("task_executor", {
            "session_id": state["session_id"],
            "token": state["token"],
            "step_index": current_step,
            "task_index": i,
            "task": task,
            "goal": state["goal"],
            "step_description": step.get("description", ""),
            "previous_results": previous_results
        })
        for i, task in enumerate(sub_tasks)
    ]
```

**How `Send()` enables parallelism:**
- 3 sub_tasks = 3 `Send("task_executor", ...)` calls
- LangGraph runs all 3 `task_executor_node` instances concurrently
- Each returns `{"results": [TaskResult(...)]}` independently
- The `add` reducer on `results` concatenates all TaskResults into one list
- `step_aggregator_node` collects the combined results

#### Task Executor — MCP tool calling

```python
# app/agent/nodes.py

async def task_executor_node(task_state: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a single task. Called in parallel for each sub_task."""
    token = task_state["token"]
    task = task_state["task"]
    tool_name = task.get("tool")
    tool_params = task.get("tool_params", {})

    if tool_name:
        # Call MCP tool via MCPClientWrapper
        tool_result = await mcp_client.call_tool(tool_name, tool_params, token)
        return {
            "results": [TaskResult(
                task_name=task.get("name"),
                tool=tool_name,
                status="success",
                result=tool_result,
                duration_ms=elapsed
            )]
        }
    else:
        # No tool — use AI to process
        result = await ai_service.execute_task(...)
        return {"results": [TaskResult(...)]}
```

#### Step Aggregator — Advance to next step or finish

```python
# app/agent/nodes.py

def step_aggregator_node(state: AgentState) -> Dict[str, Any]:
    """Check results and advance to next step."""
    results = state.get("results", [])
    current_step = state.get("current_step", 0)

    # Check for authorization failures — stop execution
    auth_failures = [r for r in results if r.get("status") == "authorization_failed"]
    if auth_failures:
        return {"status": "failed", "error": "Authorization denied"}

    # Advance to next step
    return {"current_step": current_step + 1}


def should_continue(state: AgentState) -> str:
    """Decide: continue to next step or go to summary."""
    if state.get("status") == "failed":
        return "summary"
    if state.get("current_step", 0) >= len(state.get("plan", [])):
        return "summary"    # All steps done
    return "executor"       # More steps to execute
```

### 5.5 Session Management

```python
# app/agent/graph.py — LangGraphOrchestrator

# Create a new session
session_id, initial_state, config = orchestrator.create_session_id(user_id, goal, token)

# Stream plan generation (stops at interrupt)
async for event in orchestrator.stream_graph(session_id, initial_state, config):
    yield event  # SSE events: plan_step, plan_complete

# Resume after approval (past the interrupt)
async for event in orchestrator.stream_session(session_id, config, Command(resume={"approved": True})):
    yield event  # SSE events: step_start, step_complete, execution_complete

# List user's sessions (from MongoDB checkpoints)
sessions = await orchestrator.list_user_sessions(user_id)

# Stop execution mid-stream
await orchestrator.stop_execution(session_id)

# Resume from checkpoint
async for event in orchestrator.resume_session(session_id, config):
    yield event

# Delete session
await orchestrator.delete_session(session_id)
```

---

## 6. ReAct Agent (Chat Mode)

Chat Mode uses `create_react_agent` from `langgraph-prebuilt` — the framework handles the entire think→act→observe→respond loop.

### 6.1 How It Works

```python
# app/agent/react_agent.py

async def chat_stream(
    message: str,
    token: str,
    user_id: str,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Stream a ReAct chat interaction."""

    # 1. Create Vertex AI model
    model = ChatVertexAI(
        model_name="gemini-2.5-pro",
        project="your-project",
        temperature=0,
        max_output_tokens=4096,
    )

    # 2. Load MCP tools via native streamable-http transport
    mcp = MultiServerMCPClient({
        "main": {
            "transport": "http",
            "url": "http://mcp-server:8001/mcp",
            "headers": {"Authorization": f"Bearer {token}"},
        }
    })
    tools = await mcp.get_tools()  # Returns LangChain-compatible tool objects

    # 3. Create ReAct agent with system prompt
    system_prompt = (
        "You are a helpful AI assistant with access to a database of items via MCP tools. "
        "ALWAYS use the available tools to answer questions — do not guess or refuse."
    )
    agent = create_react_agent(model, tools, prompt=system_prompt)

    # 4. Stream node-by-node updates
    async for chunk in agent.astream(
        {"messages": [("user", message)]},
        stream_mode="updates",
    ):
        for node_name, node_output in chunk.items():
            messages = node_output.get("messages", [])
            for msg in messages:
                if msg.type == "ai":
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        # AI decided to call a tool
                        for tc in msg.tool_calls:
                            yield {"type": "tool_call", "tool": tc["name"], "args": tc["args"]}
                    elif msg.content:
                        # AI generated a text response (final answer)
                        yield {"type": "response", "message": extract_text(msg.content)}

                elif msg.type == "tool":
                    # Tool execution result
                    yield {"type": "tool_result", "tool": msg.name, "result": str(msg.content)}
```

### 6.2 ReAct Loop (handled by framework)

```
User: "How many items do we have?"
  ↓
Agent Node (LLM thinks):
  → "I need to call list_items to check the database"
  → tool_calls: [{name: "list_items", args: {limit: 1000}}]
  ↓
Tools Node (MCP execution):
  → POST http://mcp-server:8001/mcp (streamable-http)
  → MCP server calls Backend: GET http://app:8000/items/
  → Returns: [{id: "...", name: "Smriti"}, ...]
  ↓
Agent Node (LLM analyzes result):
  → "There are 14 items in the database. Here they are: 1. Smriti..."
  → content: "There are 14 items..."
  ↓
Final response streamed to frontend
```

### 6.3 Gemini Content Format Handling

Gemini returns content as a list of content blocks, not plain strings:

```python
# app/agent/react_agent.py — content extraction

content = msg.content
if isinstance(content, list):
    # Gemini format: [{"type": "text", "text": "...", "thought_signature": "..."}]
    text_parts = []
    for part in content:
        if isinstance(part, dict) and "text" in part:
            text_parts.append(part["text"])
        elif isinstance(part, str):
            text_parts.append(part)
    final_response = "\n".join(text_parts)
elif isinstance(content, str):
    final_response = content
```

### 6.4 Chat Mode vs Plan Mode — Key Differences

| Feature | Plan Mode | Chat Mode |
|---------|-----------|-----------|
| Framework | LangGraph StateGraph | `create_react_agent` |
| Human Approval | Yes (interrupt) | No |
| Tool Transport | JSON-RPC `/message` | Native streamable-http `/mcp` |
| Multi-step | Yes (steps + sub_tasks) | Single turn |
| Parallel Execution | Yes (Send()) | Agent decides |
| Checkpointing | MongoDB | None (stateless) |
| Session Persistence | Yes | No |
| Best For | Complex multi-step workflows | Quick questions, single operations |

---

## 7. MongoDB & Redis Checkpointing

### 7.1 MongoDB — Cold Storage (Permanent)

LangGraph uses `MongoDBSaver` to automatically checkpoint state after every node:

```python
# app/agent/graph.py

from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

mongo_client = MongoClient("mongodb://mongodb:27017")
checkpointer = MongoDBSaver(mongo_client, db_name="mcp_demo")

# Graph compiled with checkpointer
graph = builder.compile(
    checkpointer=checkpointer,
    interrupt_before=["approval"]
)
```

**What gets stored in MongoDB:**
- Database: `mcp_demo`
- Collections: `checkpoints`, `checkpoint_writes`
- Each checkpoint contains the full `AgentState` (serialized via msgpack)
- Indexed by `thread_id` (= session_id) and `checkpoint_id` (auto-generated UUID)

**How it works:**
1. Graph execution starts → initial state saved
2. After each node completes → state saved (plan, results, status, etc.)
3. `interrupt()` → state saved, execution pauses
4. Resume → latest checkpoint loaded, execution continues
5. Session listing → query all unique `thread_id` values

```python
# Listing sessions from checkpoints
async def list_user_sessions(self, user_id: str) -> List[Dict]:
    """Get all sessions for a user from MongoDB checkpoints."""
    sessions = []
    # Get latest checkpoint per thread_id where user_id matches
    for thread_id in self._get_thread_ids():
        config = {"configurable": {"thread_id": thread_id}}
        state = self._graph.get_state(config)
        if state.values.get("user_id") == user_id:
            sessions.append({
                "session_id": thread_id,
                "goal": state.values.get("goal"),
                "status": state.values.get("status"),
            })
    return sessions
```

### 7.2 Redis — Hot Storage (Cache + Blacklist)

Redis serves two purposes:

**1. Token Blacklist:**
```python
# app/checkpoints/redis_store.py

async def blacklist_token(token: str, ttl_seconds: int = 3600):
    """Add token to blacklist (used on logout)."""
    await redis_client.setex(f"blacklist:{token}", ttl_seconds, "1")

async def is_token_blacklisted(token: str) -> bool:
    """Check if token is revoked."""
    return await redis_client.exists(f"blacklist:{token}")
```

**2. Optional Dual Checkpointing (Redis hot + MongoDB cold):**
```python
# app/agent/graph.py

if USE_DUAL_CHECKPOINTER:
    # Redis for fast reads (30-min TTL)
    from langgraph.checkpoint.redis import AsyncRedisSaver
    redis_saver = AsyncRedisSaver(conn=Redis.from_url("redis://redis:6379"))
    await redis_saver.setup()

    # MongoDB for permanent storage
    mongo_saver = MongoDBSaver(mongo_client, db_name="mcp_demo")

    # Currently uses MongoDB primary; Redis available for future hot cache
    checkpointer = mongo_saver
```

**Enable dual checkpointing:** Set `USE_DUAL_CHECKPOINTER=true` in environment.

### 7.3 Checkpoint Data Flow

```
1. Graph starts → MongoDBSaver.aput(checkpoint)
   MongoDB: checkpoints.insert_one({thread_id, checkpoint_id, state})

2. Node completes → MongoDBSaver.aput(checkpoint)
   MongoDB: checkpoints.insert_one({thread_id, checkpoint_id, state})

3. interrupt() → MongoDBSaver.aput(checkpoint)
   Execution pauses. State includes: plan, status="awaiting_approval"

4. Resume → MongoDBSaver.aget(config)
   MongoDB: checkpoints.find({thread_id}).sort({checkpoint_id: -1}).limit(1)
   Latest state loaded, execution continues from approval_node

5. Stop/Resume → Same checkpoint load mechanism
   Can resume from any saved point

6. Delete → Remove all checkpoints for thread_id
   MongoDB: checkpoints.delete_many({thread_id: session_id})
```

---

## 8. MCP Server & Tool Calling

The MCP Server is a **FastMCP** application wrapped in **FastAPI** for dual transport support.

### 8.1 Tool Definitions

Tools are defined with `@mcp.tool` decorators — FastMCP auto-generates the JSON schema from function signatures:

```python
# mcp-server/src/server.py

from fastmcp import FastMCP, Context
from pydantic import Field

mcp = FastMCP(name="AI-Experiments MCP Server")


@mcp.tool
async def create_item(
    ctx: Context,                                                    # Auto-injected by FastMCP
    name: str = Field(description="The name of the item (required)"),
    description: str = Field(default="", description="A description of the item"),
    data: dict = Field(default_factory=dict, description="Additional JSON data"),
    auth_token: str = Field(default="", description="Authorization token (auto-injected)")
) -> dict:
    """Create a new item in the database."""
    # Dual auth: native transport uses HTTP headers, JSON-RPC uses parameter
    token = _extract_token_from_context(ctx) or auth_token
    return await backend_request("POST", "/items/", token=token,
                                 json_data={"name": name, "description": description, "data": data})
```

### 8.2 Dual Auth Pattern

Every tool supports two auth paths:

```python
# mcp-server/src/server.py

def _extract_token_from_context(ctx: Context) -> str:
    """Extract auth token from native MCP HTTP request headers."""
    try:
        from fastmcp.server.dependencies import get_http_request
        request = get_http_request()
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
    except Exception:
        pass
    return ""
```

| Path | When | How Token Arrives |
|------|------|-------------------|
| Native MCP (Chat Mode) | `MultiServerMCPClient` → `POST /mcp` | HTTP `Authorization: Bearer <token>` header |
| JSON-RPC (Plan Mode) | `MCPClientWrapper` → `POST /message` | `auth_token` parameter in tool arguments |

Both paths converge at:
```python
token = _extract_token_from_context(ctx) or auth_token
```

### 8.3 Backend Request (MCP → Backend API)

Every tool calls the Backend API — never the database directly:

```python
# mcp-server/src/server.py

async def backend_request(
    method: str, path: str, token: str,
    json_data: Optional[Dict] = None, params: Optional[Dict] = None
) -> Dict[str, Any]:
    """Make an authorized request to the Backend API."""
    async with httpx.AsyncClient(base_url="http://app:8000", timeout=30.0) as client:
        response = await client.request(
            method=method, url=path,
            headers={"Authorization": f"Bearer {token}"},
            json=json_data, params=params
        )

        if response.status_code == 401:
            raise PermissionError("Unauthorized - invalid or expired token")
        if response.status_code == 403:
            detail = response.json().get("detail", "Insufficient permissions")
            raise PermissionError(f"Permission denied: {detail}")

        response.raise_for_status()
        return response.json()
```

### 8.4 JSON-RPC Wrapper (`app.py`)

The FastAPI wrapper provides backward compatibility for Plan Mode:

```python
# mcp-server/src/app.py

@app.post("/message")
async def handle_message(request: Request, authorization: Optional[str] = Header(None)):
    """Handle JSON-RPC 2.0 messages."""
    token = extract_token(authorization)
    body = await request.json()
    method = body.get("method", "")

    if method == "tools/call":
        # Validate token with backend
        if not await validate_token(token):
            raise PermissionError("Invalid or expired token")

        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        arguments_with_token = {**arguments, "auth_token": token}

        # Call tool via FastMCP
        tool_result = await mcp.call_tool(tool_name, arguments_with_token)

        # Extract text content
        content = [{"type": "text", "text": item.text} for item in tool_result.content]
        return {"jsonrpc": "2.0", "id": request_id, "result": {"content": content}}
```

### 8.5 Native MCP Endpoint (for Chat Mode)

```python
# mcp-server/src/app.py

# Create FastMCP's HTTP transport app
mcp_http = mcp.http_app()  # Returns Starlette app with /mcp route

@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    """Initialize FastMCP's StreamableHTTPSessionManager."""
    # CRITICAL: Must use same mcp_http instance for lifespan AND mount
    session_mgr = mcp_http.routes[0].endpoint.session_manager
    async with session_mgr.run():
        yield

# Mount at root — mcp_http internally serves at /mcp
app.mount("/", mcp_http)
```

**Important**: `mcp.http_app()` must be called **once** and the same instance used for both lifespan initialization and mounting. Creating two instances creates two separate session managers.

### 8.6 Available Tools

| Tool | Method | Backend Endpoint | Permission |
|------|--------|------------------|------------|
| `create_item` | POST | `/items/` | `items:write` |
| `read_item` | GET | `/items/{id}` | `items:read` |
| `update_item` | PUT | `/items/{id}` | `items:write` |
| `delete_item` | DELETE | `/items/{id}` | `items:delete` |
| `list_items` | GET | `/items/?skip=&limit=` | `items:read` |
| `search_items` | GET | `/items/search?q=` | `items:read` |

---

## 9. SSE Streaming Endpoints

All AI interactions use Server-Sent Events (SSE) for real-time streaming.

### 9.1 Chat Mode Endpoint

```python
# app/api/streaming.py

class ChatRequest(BaseModel):
    message: str

@router.post("/stream/chat")
async def stream_chat(
    request: ChatRequest,
    auth_data: Tuple[TokenData, str] = Depends(get_current_user_with_token)
):
    """Stream a ReAct chat interaction via SSE."""
    current_user, raw_token = auth_data
    mcp_token = await create_mcp_token(current_user)

    async def event_generator():
        async for event in chat_stream(request.message, mcp_token, current_user.user_id):
            yield f"data: {json.dumps(event)}\n\n"
        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**SSE Event Types (Chat Mode):**
```
data: {"type": "thinking", "message": "Connecting to MCP tools..."}
data: {"type": "thinking", "message": "Loaded 6 tools: create_item, ..."}
data: {"type": "tool_call", "tool": "list_items", "args": {"limit": 1000}}
data: {"type": "tool_result", "tool": "list_items", "result": "[{...}]"}
data: {"type": "response", "message": "There are 14 items in the database..."}
data: {"type": "done"}
```

### 9.2 Plan Mode Endpoints

```python
# app/api/streaming.py

# Create session (non-blocking)
@router.post("/stream/sessions")
async def create_streaming_session(request: CreateSessionRequest, ...)
    # Returns {session_id, goal, status: "pending"}

# Stream plan generation (SSE)
@router.get("/stream/sessions/{session_id}/plan")
async def stream_plan_generation(session_id: str, ...)
    # Starts LangGraph, streams until interrupt (plan complete)

# Stream plan execution (SSE) — resumes from interrupt
@router.get("/stream/sessions/{session_id}/execute")
async def stream_plan_execution(session_id: str, ...)
    # Resumes with Command(resume={"approved": True})

# Session management
@router.get("/stream/sessions")                         # List sessions
@router.get("/stream/sessions/{id}")                    # Get session state
@router.post("/stream/sessions/{id}/stop")              # Stop execution
@router.post("/stream/sessions/{id}/resume")            # Resume from checkpoint
@router.delete("/stream/sessions/{id}")                 # Delete session
@router.post("/stream/sessions/{id}/message")           # Add message → replan
```

**SSE Event Types (Plan Mode):**
```
data: {"type": "status", "status": "planning"}
data: {"type": "plan_step", "step": {...}}
data: {"type": "plan_complete", "plan": [...]}
data: {"type": "step_start", "step_index": 0}
data: {"type": "task_complete", "task_name": "createItem", "status": "success"}
data: {"type": "step_complete", "step_index": 0}
data: {"type": "execution_complete", "summary": {...}}
data: {"type": "error", "error": "Permission denied"}
```

---

## 10. Frontend UI

### 10.1 Mode Toggle

```jsx
// frontend/src/components/AgentPanel.jsx

const [mode, setMode] = useState('plan');  // 'plan' or 'chat'

// Mode toggle buttons
<button onClick={() => setMode('plan')} className={mode === 'plan' ? 'active' : ''}>
  📋 Plan Mode
</button>
<button onClick={() => setMode('chat')} className={mode === 'chat' ? 'active' : ''}>
  💬 Chat Mode
</button>
```

### 10.2 Chat Mode Handler

```jsx
// frontend/src/components/AgentPanel.jsx

const handleChatSend = async () => {
  const abortController = new AbortController();
  chatAbortRef.current = abortController;

  // Stream SSE from POST /stream/chat
  const response = await api.streamChat(token, chatInput, abortController.signal);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    const text = decoder.decode(value);
    // Parse SSE lines: "data: {...}\n\n"
    for (const line of text.split('\n')) {
      if (line.startsWith('data: ')) {
        const event = JSON.parse(line.slice(6));

        switch (event.type) {
          case 'thinking':
            setChatMessages(prev => [...prev, {role: 'system', content: event.message}]);
            break;
          case 'tool_call':
            setChatMessages(prev => [...prev, {role: 'tool_call', ...event}]);
            break;
          case 'tool_result':
            setChatMessages(prev => [...prev, {role: 'tool_result', ...event}]);
            break;
          case 'response':
            setChatMessages(prev => [...prev, {role: 'assistant', content: event.message}]);
            break;
          case 'error':
            setChatMessages(prev => [...prev, {role: 'error', content: event.error}]);
            break;
        }
      }
    }
  }
};
```

### 10.3 API Client

```javascript
// frontend/src/api.js

const api = {
  streamChat(token, message, signal) {
    return fetch(`${API_BASE}/stream/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ message }),
      signal,  // AbortController signal for stop button
    });
  },

  createSession(token, goal) {
    return fetch(`${API_BASE}/stream/sessions`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal }),
    });
  },

  streamPlan(token, sessionId) {
    return new EventSource(`${API_BASE}/stream/sessions/${sessionId}/plan`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
  },
};
```

---

## 11. End-to-End Request Flows

### 11.1 Chat Mode: "How many items do we have?"

```
1. User types message in Chat Mode UI
2. Frontend: POST /stream/chat {message: "How many items?"}
   Headers: Authorization: Bearer <user_jwt>

3. Backend: streaming.py
   → Validates JWT via get_current_user_with_token
   → Creates MCP token via create_mcp_token(user)
   → Calls chat_stream(message, mcp_token, user_id)

4. ReAct Agent: react_agent.py
   → Creates ChatVertexAI (Gemini model)
   → Creates MultiServerMCPClient → connects to http://mcp-server:8001/mcp
   → Loads 6 tools from MCP server
   → agent.astream({"messages": [("user", message)]})

5. Agent Node (LLM):
   → Gemini thinks: "I need to call list_items"
   → Returns tool_calls: [{name: "list_items", args: {limit: 1000}}]
   → SSE: {"type": "tool_call", "tool": "list_items"}

6. Tools Node (MCP):
   → MultiServerMCPClient → POST http://mcp-server:8001/mcp
   → MCP Server: _extract_token_from_context(ctx) → gets JWT from header
   → MCP Server: backend_request("GET", "/items/", token)
   → Backend: validate JWT → check items:read permission → query MongoDB
   → Returns: [14 items]
   → SSE: {"type": "tool_result", "tool": "list_items", "result": "[...]"}

7. Agent Node (LLM):
   → Gemini analyzes results
   → Returns: "There are 14 items in the database..."
   → SSE: {"type": "response", "message": "There are 14 items..."}

8. Frontend updates chat with all messages
```

### 11.2 Plan Mode: "Create Smriti, Engineer, US, 1000 USD"

```
1. User types goal and clicks "Create Plan"
2. Frontend: POST /stream/sessions {goal: "Create Smriti..."}
3. Backend creates session: {session_id: uuid, status: "pending"}

4. Frontend: GET /stream/sessions/{id}/plan (SSE)
5. Backend starts LangGraph:
   → planner_node: AI generates plan with 1 step
     {phase: "data_operations", tool: "create_item", tool_params: {name: "Smriti", ...}}
   → SSE: {"type": "plan_step", "step": {...}}
   → approval_node: interrupt() → state saved to MongoDB
   → SSE: {"type": "plan_complete", "plan": [...]}
   → SSE stream ends

6. User reviews plan → clicks "Execute"
7. Frontend: GET /stream/sessions/{id}/execute (SSE)
8. Backend resumes LangGraph: Command(resume={"approved": True})
   → approval_node returns: {approved: true, status: "executing"}
   → executor_dispatch: prepares step 0
   → create_task_sends: returns [Send("task_executor", {task...})]
   → task_executor_node:
     → mcp_client.call_tool("create_item", {name: "Smriti", ...}, token)
     → POST http://mcp-server:8001/message (JSON-RPC)
       {method: "tools/call", params: {name: "create_item", arguments: {..., auth_token: token}}}
     → MCP Server: mcp.call_tool("create_item", args_with_token)
     → create_item tool: token from auth_token param
     → backend_request("POST", "/items/", token, {name: "Smriti"...})
     → Backend: validate JWT → check items:write → insert MongoDB
     → Returns: {id: "...", name: "Smriti", ...}
   → SSE: {"type": "task_complete", "task_name": "createSmritiItem", "status": "success"}
   → step_aggregator: current_step = 1 → no more steps → "summary"
   → summary_node: generates execution summary
   → SSE: {"type": "execution_complete", "summary": {...}}

9. State saved to MongoDB checkpoint (entire execution history)
```

### 11.3 Permission Denied: Read-Only User Creates Item

```
1. read_only user tries: "Create an employee named John"
2. Plan generated successfully (AI doesn't check permissions)
3. User approves plan → execution starts

4. task_executor_node:
   → mcp_client.call_tool("create_item", {...}, token)
   → MCP Server: POST http://app:8000/items/ (with read_only user's token)
   → Backend: require_permission("items:write")
   → User permissions: ["items:read", "mcp:read"] — missing "items:write"
   → 403 Forbidden: "Permission denied: requires 'items:write'"

5. MCP Server: PermissionError raised in backend_request()
   → FastMCP wraps in ToolError
   → app.py catches: "Permission denied" in error message → returns 403

6. task_executor catches httpx error → status: "authorization_failed"
7. step_aggregator detects auth failure → status: "failed"
8. SSE: {"type": "error", "error": "Permission denied: requires 'items:write'"}
9. Frontend shows clear permission error to user
```

---

## 12. Debugging & Logging

### Log Prefixes

```bash
# AI flow (prompts, responses, tool calls)
docker compose logs app | grep "\[AIFLOW\]"

# LangGraph node execution
docker compose logs app | grep "langgraph"

# MCP tool calls
docker compose logs mcp-server | grep "\[create_item\]\|\[list_items\]\|\[search_items\]"

# Permission errors
docker compose logs mcp-server | grep -i "permission\|forbidden\|unauthorized"

# Request tracing (every request gets unique ID)
docker compose logs app | grep "req:abc123"
```

### Container Logs

```bash
docker compose logs -f              # All services, follow
docker compose logs -f app          # Backend only
docker compose logs -f mcp-server   # MCP server only
docker compose logs --tail 50 app   # Last 50 lines
```

### Health Checks

```bash
curl http://localhost:8000/health           # Backend
curl http://localhost:8001/health           # MCP Server
curl http://localhost:8001/tools            # List MCP tools
```

### Test Tool Call Directly

```bash
# Login and get token
TOKEN=$(curl -s http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"testuser","password":"testpass"}' | jq -r .access_token)

# Call MCP tool via JSON-RPC
curl -X POST http://localhost:8001/message \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": "test1",
    "method": "tools/call",
    "params": {
      "name": "list_items",
      "arguments": {"skip": 0, "limit": 10}
    }
  }'
```

---

## 13. Common Tasks

### Adding a New MCP Tool

**1. Define the tool** in `mcp-server/src/server.py`:

```python
@mcp.tool
async def my_new_tool(
    ctx: Context,
    param1: str = Field(description="What this param does"),
    auth_token: str = Field(default="", description="Authorization token (auto-injected)")
) -> dict:
    """Description of what this tool does."""
    token = _extract_token_from_context(ctx) or auth_token
    return await backend_request("GET", "/my-endpoint", token=token, params={"q": param1})
```

**2. Add the backend endpoint** in `app/api/items_routes.py` (if needed)

**3. That's it!** FastMCP auto-generates the schema. Both transports work automatically.

### Adding a New Role

**1. Define role** in `app/models/schemas.py`:
```python
class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"
    READ_ONLY = "read_only"
    MANAGER = "manager"  # New role
```

**2. Set permissions** in `app/auth/authorization.py`:
```python
ROLE_PERMISSIONS = {
    ...
    UserRole.MANAGER: ["items:read", "items:write", "agent:execute", "mcp:read", "mcp:write"]
}
```

### Restarting Services

```bash
docker compose build app && docker compose up -d app        # Single service
docker compose down && docker compose up -d                  # All services
docker compose build --no-cache && docker compose up -d      # Full rebuild
```

---

## 14. Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MONGODB_URL` | MongoDB connection string | `mongodb://mongodb:27017` |
| `MONGODB_DATABASE` | Database name | `mcp_demo` |
| `REDIS_URL` | Redis connection string | `redis://redis:6379` |
| `JWT_SECRET_KEY` | Secret for JWT signing | **Required** |
| `JWT_ALGORITHM` | JWT algorithm | `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Token TTL | `30` |
| `GOOGLE_CLOUD_PROJECT` | GCP project for Vertex AI | **Required** |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI region | `us-central1` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON | `/app/credentials/service-account.json` |
| `VERTEXAI_MODEL` | Gemini model name | `gemini-2.5-pro` |
| `MCP_SERVER_URL` | MCP server internal URL | `http://mcp-server:8001` |
| `BACKEND_URL` | Backend API URL (for MCP server) | `http://app:8000` |
| `USE_DUAL_CHECKPOINTER` | Enable Redis+MongoDB dual checkpointing | `false` |

---

## 15. Troubleshooting

### "500 Internal Server Error" on tool call

**Likely cause:** Permission error wrapped as 500.
**Fix:** Check MCP server logs: `docker compose logs mcp-server | grep -i error`
- If "Permission denied" → user lacks required permission (e.g., read_only user creating items)
- Use a user with appropriate role

### "AI service initialization failed"

- Check `credentials/service-account.json` exists
- Verify `GOOGLE_CLOUD_PROJECT` is set in `.env`
- Ensure GCP project has Vertex AI API enabled

### "Token has been revoked"

- User logged out — token added to Redis blacklist
- Log in again to get a fresh token

### "MCP Server connection failed"

```bash
docker compose ps                       # Check all containers running
docker compose logs mcp-server          # Check MCP server startup
curl http://localhost:8001/health       # Test MCP server directly
```

### Plan execution hangs

- Check SSE stream isn't blocked: backend log should show streaming events
- Verify Vertex AI is responding: `docker compose logs app | grep "\[AIFLOW\]"`
- Ensure MCP server is reachable: `docker compose exec app curl http://mcp-server:8001/health`

### Chat Mode returns "No response generated"

- AI model might not have called tools. Check system prompt in `react_agent.py`
- Verify MCP tools are loading: look for "Loaded 6 tools" in SSE events
- Check model credentials and quota

---

## References

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [FastMCP Documentation](https://gofastmcp.com/)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Vertex AI Gemini](https://cloud.google.com/vertex-ai/docs/generative-ai/model-reference/gemini)
- [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters)
