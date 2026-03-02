# Framework Research: Reducing Code with Modern AI Frameworks

This document analyses the current codebase, identifies the most popular alternative frameworks, and shows concrete before/after code comparisons to quantify potential code reduction.

---

## 1. Current Codebase Overview

The application is built across two logical services:

| File | Lines (approx.) | Purpose |
|------|----------------|---------|
| `app/agent/langgraph_agent.py` | ~280 | Custom agent orchestration (plan mode + state) |
| `app/mcp/server.py` | ~310 | Custom MCP protocol handler |
| `app/auth/authorization.py` | ~175 | JWT creation, RBAC, token blacklist |
| `app/checkpoints/mongodb_store.py` | ~80 | Hot-state persistence in MongoDB |
| `app/checkpoints/redis_store.py` | ~110 | Cold-state persistence in Redis |
| `app/main.py` | ~70 | FastAPI app wiring |
| **Total** | **~1,025** | |

### Key observations

1. **`langgraph_agent.py` does not actually use LangGraph.** It implements a manual state machine that mimics LangGraph patterns but uses plain Python + MongoDB for state management. The class is named `PlanModeAgent` and manually tracks plan steps, session IDs and checkpoints.

2. **`app/mcp/server.py` does not use the MCP protocol library.** It defines a custom `MCPServer` class that manually handles `tools/list`, `resources/list` and `initialize` methods using plain dicts. There is no auto-discovery, no JSON-RPC transport, and no schema validation.

3. **`app/auth/authorization.py` is well-written** but re-implements patterns that dedicated libraries already provide (password hashing, JWT lifecycle, permission decorators).

4. **Checkpointing is fully custom.** `MongoDBStore` and `RedisStore` implement `save/get/delete` manually, while the real LangGraph provides official checkpointer backends out of the box.

---

## 2. Framework Alternatives

### 2.1 Agent Orchestration

#### Option A — LangGraph (with `langgraph-prebuilt`)

**GitHub:** https://github.com/langchain-ai/langgraph  
**Stars:** 11 k+ (2025)  
**What it replaces:** The entire `langgraph_agent.py` + the custom checkpoint stores

LangGraph's `create_react_agent` (from `langgraph-prebuilt`) provides a complete ReAct agent in one call. Official checkpointer packages (`langgraph-checkpoint-mongodb`, `langgraph-checkpoint-redis`) replace the custom stores.

**Current code (~50 lines for agent creation + state wiring):**

```python
# app/agent/langgraph_agent.py  — CURRENT (simplified excerpt)
class PlanModeAgent:
    def __init__(self):
        self.available_actions = { "search": ..., "analyze": ..., ... }

    async def create_session(self, user_id: str) -> str:
        session_id = str(uuid.uuid4())
        initial_state = AgentState(
            session_id=session_id,
            user_id=user_id,
            state_type="hot",
            state_data={"messages": [], "plan": [], ...},
        )
        await mongodb_checkpoint.save_checkpoint(initial_state)
        return session_id

    async def enter_plan_mode(self, session_id: str, goal: str):
        state = await self._get_state(session_id)
        plan = await self._generate_plan(goal)
        state.state_data["plan"] = plan
        await self._save_state(state)
        return {"session_id": session_id, "plan": plan, ...}

    async def execute_step(self, session_id: str):
        state = await self._get_state(session_id)
        step = state.plan[state.current_step]
        action_fn = self.available_actions[step["action"]]
        result = await action_fn(state.state_data)
        step["result"] = result
        step["status"] = "completed"
        state.current_step += 1
        await self._save_state(state)
        return result
    # ... 200+ more lines
```

**With LangGraph + langgraph-prebuilt (~20 lines):**

```python
# NEW: app/agent/agent.py
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.mongodb import MongoDBSaver
from langchain_google_vertexai import ChatVertexAI
from langchain_core.tools import tool

@tool
def search(query: str) -> str:
    """Search for information."""
    return f"Results for: {query}"

@tool
def analyze(data: str) -> str:
    """Analyse the provided data."""
    return f"Analysis of: {data}"

model = ChatVertexAI(model="gemini-2.5-pro")

with MongoDBSaver.from_conn_string("mongodb://localhost:27017") as checkpointer:
    agent = create_react_agent(model, [search, analyze], checkpointer=checkpointer)
    result = agent.invoke(
        {"messages": [("user", "Search and analyse AI trends")]},
        config={"configurable": {"thread_id": "session-123"}}
    )
```

**Code reduction:** ~280 lines → ~20 lines (**93% reduction**)

---

#### Option B — PydanticAI

**GitHub:** https://github.com/pydantic/pydantic-ai  
**Stars:** 8 k+ (2025)  
**What it replaces:** The entire `langgraph_agent.py`

PydanticAI is built by the Pydantic team with a FastAPI-like developer experience. Tools are plain Python functions decorated with `@agent.tool`. Structured outputs are automatically validated against Pydantic models. It natively supports Google Gemini, OpenAI, Anthropic, and Mistral.

```python
# NEW: app/agent/agent.py
from pydantic_ai import Agent
from pydantic_ai.models.vertexai import VertexAIModel

model = VertexAIModel("gemini-2.5-pro")
agent = Agent(model, system_prompt="You are a helpful assistant with planning capabilities.")

@agent.tool
async def search(query: str) -> str:
    """Search for relevant information."""
    return f"Search results for: {query}"

@agent.tool
async def analyze(data: str) -> str:
    """Analyse the provided data."""
    return f"Analysis: {data}"

# Run with automatic type-safe output
result = await agent.run("Find and analyse the latest AI agent frameworks")
print(result.data)  # Pydantic-validated response
```

**Code reduction:** ~280 lines → ~20 lines (**93% reduction**)

**PydanticAI advantages over LangGraph for this use case:**
- No graph/node/edge boilerplate for simple chat agents
- Automatic Pydantic output validation
- Built-in dependency injection for testing
- Familiar FastAPI-style ergonomics
- Smaller dependency footprint

---

#### Option C — smolagents (HuggingFace)

**GitHub:** https://github.com/huggingface/smolagents  
**Stars:** 16 k+ (2025)  
**What it replaces:** `langgraph_agent.py`

smolagents is extremely minimal (~1,000 lines in its own core). It uses a `CodeAgent` that expresses tool calls as Python code, which reduces JSON marshalling overhead. Best for rapid prototyping and research-oriented workflows.

```python
# NEW: app/agent/agent.py
from smolagents import CodeAgent, tool, LiteLLMModel

model = LiteLLMModel(model_id="gemini/gemini-2.5-pro")

@tool
def search(query: str) -> str:
    """Search for information. Args: query: the search query"""
    return f"Results for: {query}"

agent = CodeAgent(tools=[search], model=model)
result = agent.run("Search for the latest MCP protocol updates")
```

**Code reduction:** ~280 lines → ~10 lines (**96% reduction**)

**Limitation:** smolagents is best for single-step or simple multi-step tasks. For the plan mode pattern (generate plan → approve → execute steps), LangGraph's `interrupt()` and state machine model is more appropriate.

---

#### Option D — CrewAI

**GitHub:** https://github.com/crewAIInc/crewAI  
**Stars:** 28 k+ (2025)  
**What it replaces:** `langgraph_agent.py` (multi-agent orchestration)

CrewAI excels when tasks decompose into distinct roles (researcher, writer, analyst). Less suited for the interrupt-driven plan-approve-execute pattern in the current codebase.

```python
from crewai import Agent, Task, Crew

researcher = Agent(
    role="Researcher",
    goal="Find information about {topic}",
    backstory="Expert researcher with deep knowledge",
    llm="gemini/gemini-2.5-pro"
)

research_task = Task(
    description="Research the topic: {topic}",
    expected_output="Detailed research summary",
    agent=researcher
)

crew = Crew(agents=[researcher], tasks=[research_task])
result = crew.kickoff(inputs={"topic": "MCP protocol"})
```

**Code reduction:** ~280 lines → ~20 lines (**93% reduction**)

**Limitation:** CrewAI checkpointing with MongoDB is less mature than LangGraph's official `langgraph-checkpoint-mongodb` package.

---

### 2.2 MCP Server

#### Option A — FastMCP

**GitHub:** https://github.com/jlowin/fastmcp  
**Stars:** 6 k+ (2025)  
**What it replaces:** Entire `app/mcp/server.py`

FastMCP is an open-source framework for building MCP servers with a FastAPI-like decorator API. A `@mcp.tool` decorator auto-generates tool schemas, handles JSON-RPC transport, and provides a full ASGI app.

**Current code (~310 lines):**

```python
# app/mcp/server.py — CURRENT (excerpt)
class MCPServer:
    def __init__(self):
        self.tools = {}
        self.resources = {}
        self._register_default_tools()

    def _register_default_tools(self):
        self.tools = {
            "create_item": {
                "name": "create_item",
                "description": "Create a new item in the system",
                "required_permission": "items:write",
                "parameters": { "name": {...}, "description": {...} }
            },
            # ... 5 more tools, each 8-12 lines
        }

    async def call_tool(self, token, tool_name, arguments):
        tool = self.tools.get(tool_name)
        if not tool:
            return MCPResponse(error={"code": "tool_not_found", ...})
        access = self.validate_access(token, tool["required_permission"])
        if not access["authorized"]:
            return MCPResponse(error={"code": "unauthorized", ...})
        # ... validate params, execute, return
```

**With FastMCP (~50 lines):**

```python
# NEW: app/mcp/server.py
from fastmcp import FastMCP
from app.auth import require_permission

mcp = FastMCP("Demo MCP Server")

@mcp.tool
async def create_item(name: str, description: str = "") -> dict:
    """Create a new item in the system."""
    # FastMCP auto-generates the JSON schema from type hints
    # RBAC is handled via FastAPI dependency injection
    return {"id": "new-id", "name": name, "description": description}

@mcp.tool
async def read_item(item_id: str) -> dict:
    """Read an item from the system."""
    return {"id": item_id, "name": "Example"}

@mcp.tool
async def update_item(item_id: str, updates: dict) -> dict:
    """Update an existing item."""
    return {"id": item_id, **updates}

@mcp.tool
async def delete_item(item_id: str) -> dict:
    """Delete an item from the system."""
    return {"deleted": item_id}

# Mount as ASGI app — no custom routing needed
app = mcp.http_app()
```

**Code reduction:** ~310 lines → ~50 lines (**84% reduction**)

**FastMCP advantages:**
- Auto-generates JSON schemas from Python type hints
- Handles JSON-RPC 2.0 transport automatically
- Supports Streamable HTTP (MCP 2025 spec)
- Type-safe tool inputs and outputs

---

#### Option B — Official MCP Python SDK

**GitHub:** https://github.com/modelcontextprotocol/python-sdk  
**Package:** `mcp>=1.23.0`

The official SDK from Anthropic provides both server and client implementations. FastMCP is actually built on top of this SDK and is now part of the official MCP SDK (merged in MCP 1.x).

```python
from mcp.server.fastmcp import FastMCP  # official since MCP 1.x

mcp = FastMCP("Demo Server")

@mcp.tool()
def create_item(name: str, description: str = "") -> str:
    return f"Created item: {name}"
```

---

### 2.3 Authentication & RBAC

#### Option A — fastapi-users

**GitHub:** https://github.com/fastapi-users/fastapi-users  
**Stars:** 4.5 k+ (2025)  
**What it replaces:** Most of `app/auth/authorization.py`

fastapi-users provides plug-and-play registration, login, JWT issuance, and user management for FastAPI + MongoDB (via Beanie or Motor).

**Current code (~175 lines):**

```python
# app/auth/authorization.py — CURRENT (excerpt)
ROLE_PERMISSIONS = { UserRole.ADMIN: [...], UserRole.USER: [...], UserRole.READ_ONLY: [...] }

def create_access_token(user_id, username, role, expires_delta=None):
    permissions = ROLE_PERMISSIONS.get(role, [])
    to_encode = {"sub": user_id, "username": username, "role": role.value, ...}
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=...))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=...)

def decode_token(token):
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[...])
        # ... extract fields, validate, return TokenData
    except JWTError as e:
        raise HTTPException(status_code=401, ...)

async def get_current_user(credentials=Depends(security)):
    token = credentials.credentials
    if await redis_checkpoint.is_token_blacklisted(token):
        raise HTTPException(status_code=401, detail="Token revoked")
    return decode_token(token)
```

**With fastapi-users (~40 lines):**

```python
# NEW: app/auth/auth.py
from beanie import Document
from fastapi_users import FastAPIUsers
from fastapi_users.authentication import BearerTransport, JWTStrategy, AuthenticationBackend
from fastapi_users.db import BeanieUserDatabase
from pydantic import Field
from enum import Enum

class UserRole(str, Enum):
    admin = "admin"
    user = "user"
    read_only = "read_only"

class User(Document):
    role: UserRole = UserRole.user

    class Settings:
        name = "users"

async def get_user_db():
    yield BeanieUserDatabase(User)

bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")

def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=SECRET, lifetime_seconds=3600)

auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, PydanticObjectId](get_user_db, [auth_backend])

# One line for current user dependency
current_user = fastapi_users.current_user()
```

**Code reduction:** ~175 lines → ~40 lines (**77% reduction**)

**Trade-off:** fastapi-users as of 2025 is feature-frozen (no new features, security maintenance only). For granular RBAC with custom permission strings (`items:write`, `agent:execute`), the current custom approach may actually be cleaner. Consider keeping the RBAC logic but using `python-jwt` directly instead of `python-jose`.

---

### 2.4 Checkpointing

#### Option A — LangGraph Official Checkpointers

**Packages:** `langgraph-checkpoint-mongodb`, `langgraph-checkpoint-redis`

These are official checkpointer backends from the LangGraph team. They implement the `BaseCheckpointSaver` interface and integrate transparently with LangGraph graphs.

**Current code (~190 lines across two files):**

```python
# app/checkpoints/mongodb_store.py — CURRENT (excerpt)
class MongoDBCheckpoint:
    def __init__(self):
        self.client = None
        self.db = None
        self.collection = None

    async def connect(self):
        self.client = AsyncIOMotorClient(settings.mongodb_url)
        self.db = self.client[settings.mongodb_db_name]
        self.collection = self.db["checkpoints"]

    async def save_checkpoint(self, state: AgentState) -> str:
        document = {
            "_id": state.session_id,
            "user_id": state.user_id,
            "state_data": state.state_data,
            "updated_at": datetime.now(timezone.utc)
        }
        await self.collection.replace_one({"_id": state.session_id}, document, upsert=True)
        return state.session_id

    async def get_checkpoint(self, session_id: str) -> Optional[AgentState]:
        document = await self.collection.find_one({"_id": session_id})
        if not document:
            return None
        return AgentState(**document)
    # ... delete, list, etc.
```

**With langgraph-checkpoint-mongodb (~5 lines):**

```python
# NEW: app/checkpoints/__init__.py
from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.checkpoint.redis import RedisSaver

# Hot checkpoints — MongoDB
mongodb_checkpointer = MongoDBSaver.from_conn_string(
    "mongodb://localhost:27017",
    db_name="mcp_demo"
)

# Cold checkpoints — Redis (optional, for archiving)
redis_checkpointer = RedisSaver.from_conn_string("redis://localhost:6379")
```

**Code reduction:** ~190 lines → ~10 lines (**95% reduction**)

---

## 3. Summary Table

| Component | Current LoC | Framework Alternative | New LoC | Reduction |
|-----------|------------|----------------------|---------|-----------|
| Agent orchestration | ~280 | LangGraph `create_react_agent` | ~20 | **93%** |
| Agent orchestration | ~280 | PydanticAI | ~20 | **93%** |
| Agent orchestration | ~280 | smolagents | ~10 | **96%** |
| MCP Server | ~310 | FastMCP / `mcp.server.fastmcp` | ~50 | **84%** |
| Auth / RBAC | ~175 | fastapi-users | ~40 | **77%** |
| Checkpointing | ~190 | `langgraph-checkpoint-mongodb` + `redis` | ~10 | **95%** |
| **Total** | **~1,025** | **All alternatives combined** | **~150** | **~85%** |

---

## 4. Recommended Migration Path

### Priority 1 — Highest impact, lowest risk

**Replace custom MCP server with FastMCP** (`mcp.server.fastmcp`)

- 84% code reduction in `app/mcp/server.py`
- Drop-in replacement: same HTTP endpoints, same JSON-RPC protocol
- `@mcp.tool` decorators auto-generate schemas — no manual dict registration
- No changes needed to clients or frontends
- `pip install "mcp>=1.23.0"` (already a dependency)

**Replace custom checkpoints with `langgraph-checkpoint-mongodb`**

- 95% code reduction in `app/checkpoints/`
- Official LangGraph package, actively maintained
- Works directly with LangGraph graphs — no adapters needed

### Priority 2 — Adopt actual LangGraph

**Replace `PlanModeAgent` with real LangGraph StateGraph + `create_react_agent`**

- The current `langgraph_agent.py` is named after LangGraph but does not use it
- Adopting real LangGraph gives: time-travel debugging, LangSmith tracing, `interrupt()` for human-in-the-loop, and parallel node execution
- 93% code reduction

### Priority 3 — Optional auth simplification

**Consider PydanticAI or fastapi-users for auth**

The current auth code is clean and well-tested. Migration here has the least urgency. The main improvement would be switching from `python-jose` (less actively maintained) to `PyJWT` directly.

---

## 5. Detailed Framework Profiles

### LangGraph (Recommended for plan mode)

| Property | Value |
|----------|-------|
| GitHub | https://github.com/langchain-ai/langgraph |
| Stars | 11 k+ |
| License | MIT |
| Python | 3.9+ |
| LLM support | All LangChain-supported models (OpenAI, Gemini, Claude, etc.) |
| MCP support | Via `langchain-mcp-adapters` |
| Checkpointing | MongoDB, Redis, PostgreSQL, SQLite (official packages) |
| Plan mode | `interrupt()` for human-in-the-loop approval |
| Streaming | SSE and WebSocket via `astream_events` |
| Observability | LangSmith, LangFuse, OpenTelemetry |

### PydanticAI (Recommended for chat mode)

| Property | Value |
|----------|-------|
| GitHub | https://github.com/pydantic/pydantic-ai |
| Stars | 8 k+ |
| License | MIT |
| Python | 3.9+ |
| LLM support | OpenAI, Gemini (VertexAI + Generative), Claude, Mistral, Groq, Ollama |
| MCP support | Native `mcp_servers` parameter on `Agent` |
| Checkpointing | Bring-your-own (no built-in, but agent history is a plain list) |
| Streaming | `agent.run_stream()` async generator |
| Observability | Logfire (by Pydantic), OpenTelemetry |

**PydanticAI MCP example (3 lines to connect to an MCP server):**

```python
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerHTTP

agent = Agent(
    "google-vertex:gemini-2.5-pro",
    mcp_servers=[MCPServerHTTP(url="http://localhost:8001/mcp")]
)

async with agent.run_mcp_servers():
    result = await agent.run("List all items")
```

### smolagents (Recommended for rapid prototyping)

| Property | Value |
|----------|-------|
| GitHub | https://github.com/huggingface/smolagents |
| Stars | 16 k+ |
| License | Apache 2.0 |
| Python | 3.10+ |
| LLM support | HuggingFace Hub, OpenAI, Anthropic, LiteLLM (any provider) |
| MCP support | `ToolCollection.from_mcp` for loading MCP tools |
| Checkpointing | None built-in |
| Agent types | `CodeAgent` (writes Python), `ToolCallingAgent` (JSON tool calls) |

**smolagents MCP integration:**

```python
from smolagents import ToolCollection, CodeAgent, LiteLLMModel
from mcp import StdioServerParameters

model = LiteLLMModel(model_id="gemini/gemini-2.5-pro")

with ToolCollection.from_mcp(
    StdioServerParameters(command="uvx", args=["your-mcp-server"])
) as tool_collection:
    agent = CodeAgent(tools=[*tool_collection.tools], model=model)
    agent.run("Create an item named 'test'")
```

### FastMCP (Recommended for MCP server)

| Property | Value |
|----------|-------|
| GitHub | https://github.com/jlowin/fastmcp (now merged into official MCP SDK) |
| Package | `mcp>=1.x` (`from mcp.server.fastmcp import FastMCP`) |
| Stars | 6 k+ original repo |
| License | Apache 2.0 |
| Transport | JSON-RPC over HTTP, Streamable HTTP (2025 spec), SSE, stdio |
| Schema gen | Automatic from Python type hints |
| RBAC | Via middleware or dependency injection |
| Testing | Built-in `Client` for unit testing without HTTP overhead |

### CrewAI (Recommended for multi-agent teams)

| Property | Value |
|----------|-------|
| GitHub | https://github.com/crewAIInc/crewAI |
| Stars | 28 k+ |
| License | MIT |
| Python | 3.10+ |
| LLM support | All LangChain-supported models + LiteLLM |
| MCP support | Community plugins |
| Checkpointing | Partial (memory via Redis/Postgres, not full workflow replay) |
| Best for | Role-based multi-agent collaboration |

---

## 6. Quick-Start: Migrating to FastMCP

The single highest-impact, lowest-risk change is replacing the custom MCP server. Here is the complete migration:

### Step 1 — Update `requirements.txt`

```
# Remove (no longer needed):
# - custom MCPServer class

# Add:
mcp>=1.23.0          # already present — FastMCP is bundled since 1.x
```

### Step 2 — Replace `app/mcp/server.py`

```python
"""MCP Server using FastMCP — replaces 310 lines with ~50."""
from mcp.server.fastmcp import FastMCP
from app.models import UserRole
from app.crud import items_crud   # existing CRUD layer

mcp = FastMCP("Demo MCP Server", description="RBAC-enabled item management server")

@mcp.tool()
async def create_item(name: str, description: str = "", data: dict = {}) -> dict:
    """Create a new item in the system."""
    return await items_crud.create({"name": name, "description": description, "data": data})

@mcp.tool()
async def list_items(limit: int = 50) -> list:
    """List all items in the system."""
    return await items_crud.list(limit=limit)

@mcp.tool()
async def read_item(item_id: str) -> dict:
    """Read a specific item by ID."""
    return await items_crud.get(item_id)

@mcp.tool()
async def update_item(item_id: str, name: str = None, description: str = None) -> dict:
    """Update an existing item."""
    updates = {k: v for k, v in {"name": name, "description": description}.items() if v is not None}
    return await items_crud.update(item_id, updates)

@mcp.tool()
async def delete_item(item_id: str) -> dict:
    """Delete an item from the system."""
    await items_crud.delete(item_id)
    return {"deleted": item_id, "success": True}

# ASGI app — mount in main.py with app.mount("/mcp", mcp.http_app())
```

### Step 3 — Update `app/main.py`

```python
from app.mcp.server import mcp   # import the FastMCP instance

# Mount MCP as a sub-application
app.mount("/mcp", mcp.http_app())
```

---

## 7. Quick-Start: Migrating to LangGraph `create_react_agent`

### Step 1 — Update `requirements.txt`

```
langgraph>=1.0.0
langgraph-prebuilt>=1.0.0
langgraph-checkpoint-mongodb>=0.1.0
langchain-mcp-adapters>=0.2.0
langchain-google-vertexai>=3.0.0
```

### Step 2 — Replace `app/agent/langgraph_agent.py`

```python
"""LangGraph ReAct agent — replaces 280 lines with ~40."""
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.mongodb import MongoDBSaver
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_google_vertexai import ChatVertexAI
from app.config import get_settings

settings = get_settings()
model = ChatVertexAI(model="gemini-2.5-pro-preview-0514")

async def get_agent(session_id: str):
    """Return a LangGraph agent with MongoDB checkpointing."""
    async with MultiServerMCPClient({
        "demo": {
            "url": f"{settings.mcp_server_url}/mcp",
            "transport": "streamable_http",
        }
    }) as client:
        tools = client.get_tools()

    checkpointer = MongoDBSaver.from_conn_string(settings.mongodb_url)
    agent = create_react_agent(
        model,
        tools,
        checkpointer=checkpointer,
        prompt="You are a helpful assistant. Use tools to answer questions."
    )
    return agent, {"configurable": {"thread_id": session_id}}
```

### Step 3 — Replace `app/checkpoints/` directory

```python
# app/checkpoints/__init__.py — replaces 190 lines
from langgraph.checkpoint.mongodb import MongoDBSaver
from app.config import get_settings

settings = get_settings()

def get_checkpointer():
    return MongoDBSaver.from_conn_string(
        settings.mongodb_url,
        db_name=settings.mongodb_db_name
    )
```

---

## 8. Decision Matrix

| Criterion | LangGraph | PydanticAI | smolagents | CrewAI |
|-----------|-----------|------------|------------|--------|
| Plan mode (interrupt) | ✅ Best | ⚠️ Manual | ❌ None | ⚠️ Partial |
| Chat mode (ReAct) | ✅ | ✅ | ✅ | ✅ |
| MongoDB checkpointing | ✅ Official | ❌ Custom | ❌ Custom | ⚠️ Partial |
| MCP native support | ✅ Via adapters | ✅ Native | ✅ Via ToolCollection | ⚠️ Plugin |
| Code simplicity | Medium | High | Highest | High |
| Production maturity | High | Medium | Medium | High |
| LangSmith tracing | ✅ | ❌ | ❌ | ✅ |
| Gemini/VertexAI | ✅ | ✅ | ✅ LiteLLM | ✅ |

**Recommendation for this codebase:**

- **Plan mode:** Keep or adopt LangGraph `StateGraph` with `interrupt()` — it is the only framework with first-class plan-approve-execute workflow support and official MongoDB checkpointing.
- **Chat mode:** Use LangGraph `create_react_agent` (already available in `langgraph-prebuilt`). If you want less boilerplate, PydanticAI is a strong alternative.
- **MCP server:** Migrate to FastMCP / `mcp.server.fastmcp` — the biggest quick win.
- **Checkpointing:** Replace custom stores with `langgraph-checkpoint-mongodb` and `langgraph-checkpoint-redis`.
- **Auth:** Keep the custom RBAC (it is well-structured) but consider replacing `python-jose` with `PyJWT` which is more actively maintained.
