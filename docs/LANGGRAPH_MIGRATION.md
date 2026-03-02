# LangGraph Migration Plan

## Executive Summary

After extensive research, here are the recommended frameworks for replacing our custom code:

| Component | Current | Recommended | Alternative |
|-----------|---------|-------------|-------------|
| **Agent Orchestration** | Custom `multi_agent.py` | **LangGraph** | CrewAI, Agno |
| **MCP Server** | Custom Python | **FastMCP** | mcp-framework (TS) |
| **MCP Client** | Custom `mcp/client.py` | **langchain-mcp-adapters** | mcp-use |
| **Checkpointing** | Custom MongoDB/Redis | **langgraph-checkpoint-mongodb** | Built-in |
| **Authorization** | Custom JWT | **FastMCP BearerAuthProvider** | Keep custom |

---

## Agent Framework Comparison (2024-2025)

### 1. LangGraph ⭐ RECOMMENDED

| Aspect | Details |
|--------|---------|
| **Architecture** | Graph-based state machines (DAG) |
| **Strengths** | Deterministic workflows, built-in checkpointing, interrupts for HITL |
| **Weaknesses** | Steeper learning curve |
| **Best For** | Our use case - complex multi-step with approval |

```python
from langgraph.graph import StateGraph
from langgraph.checkpoint.mongodb.aio import AsyncMongoDBSaver

builder = StateGraph(AgentState)
builder.add_node("planner", planner_node)
builder.add_node("approval", approval_node)  # interrupt()
builder.add_node("executor", executor_node)
graph = builder.compile(checkpointer=AsyncMongoDBSaver(...))
```

### 2. CrewAI

| Aspect | Details |
|--------|---------|
| **Architecture** | Role-based teams (Crews + Flows) |
| **Strengths** | Easy setup, team-like API, 5.76x faster than LangGraph in some benchmarks |
| **Weaknesses** | Less suited for complex branching |
| **Best For** | Simple pipelines with clear roles |

```python
from crewai import Agent, Crew, Task

researcher = Agent(role="Researcher", goal="Find data", tools=[...])
crew = Crew(agents=[researcher], tasks=[...])
result = crew.kickoff()
```

### 3. Agno (NEW - 2025)

| Aspect | Details |
|--------|---------|
| **Architecture** | Modern Python framework with AgentOS |
| **Strengths** | Built-in MCP support, production-ready FastAPI backend, tracing UI |
| **Weaknesses** | Newer, smaller community |
| **Best For** | Quick deployment with monitoring |

```python
from agno.agent import Agent
from agno.tools.mcp import MCPTools
from agno.os import AgentOS

agent = Agent(
    name="Assistant",
    model=Claude(id="claude-sonnet-4-6"),
    tools=[MCPTools(url="http://mcp-server:8001")]
)
app = AgentOS(agents=[agent]).get_app()
```

### 4. AutoGen (Microsoft)

| Aspect | Details |
|--------|---------|
| **Architecture** | Multi-agent conversation (group chat) |
| **Strengths** | Flexible, Azure integration, visual debugging |
| **Weaknesses** | Less reproducible, being folded into new Microsoft Agent Framework |
| **Best For** | Research, experimentation |

### Framework Decision Matrix

| Requirement | LangGraph | CrewAI | Agno | AutoGen |
|-------------|-----------|--------|------|---------|
| Human-in-the-loop | ✅ Native `interrupt()` | ⚠️ Manual | ✅ Approval flows | ✅ HITL support |
| MongoDB checkpoints | ✅ `AsyncMongoDBSaver` | ❌ Custom needed | ✅ Built-in | ⚠️ Custom |
| MCP integration | ✅ `langchain-mcp-adapters` | ⚠️ Manual | ✅ Native `MCPTools` | ⚠️ Manual |
| Parallel execution | ✅ `Send()` pattern | ✅ Parallel tasks | ✅ Async | ✅ Concurrent agents |
| SSE streaming | ✅ `astream()` | ⚠️ Custom | ✅ Built-in | ⚠️ Custom |
| Production ready | ✅ LangSmith | ⚠️ Basic | ✅ AgentOS UI | ⚠️ Studio |

**Winner: LangGraph** - Best fit for our requirements (HITL approval, MongoDB checkpoints, MCP tools, streaming)

---

## MCP Framework Comparison

### 1. FastMCP ⭐ RECOMMENDED for Server

| Aspect | Details |
|--------|---------|
| **Language** | Python |
| **Auth Support** | API Key, JWT Bearer, OAuth 2.1 |
| **Strengths** | Most popular Python MCP framework, built-in auth middleware |

```python
from fastmcp import FastMCP
from fastmcp.server.auth import BearerAuthProvider

mcp = FastMCP(auth_provider=BearerAuthProvider(public_key=public_key))

@mcp.tool()
def create_item(ctx, name: str, description: str):
    if not ctx.user.has_scope("items:write"):
        raise Exception("Forbidden")
    # Tool logic
```

### 2. mcp-framework (TypeScript/npm)

| Aspect | Details |
|--------|---------|
| **Language** | TypeScript |
| **Strengths** | CLI tooling, auto-discovery, type safety with Zod |
| **Best For** | Node.js ecosystems, IDE integrations |

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp";
import { z } from "zod";

const server = new McpServer({ name: "demo", version: "1.0.0" });
server.tool("add", { a: z.number(), b: z.number() }, async ({ a, b }) => ({
  content: [{ type: "text", text: `${a + b}` }]
}));
```

### 3. langchain-mcp-adapters ⭐ RECOMMENDED for Client

| Aspect | Details |
|--------|---------|
| **Purpose** | MCP client for LangChain/LangGraph |
| **Strengths** | Multi-server support, converts MCP tools to LangChain format |

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "items_server": {
        "url": "http://mcp-server:8001/mcp",
        "transport": "http",
        "headers": {"Authorization": "Bearer <token>"}
    }
})
tools = await client.get_tools()
```

### 4. mcp-use (Python)

| Aspect | Details |
|--------|---------|
| **Purpose** | Lightweight Python MCP server/client |
| **Strengths** | Minimal setup, FastAPI integration |

---

## Updated Migration Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React)                                 │
│   AgentPanel.jsx ─── EventSource for SSE streaming                      │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    BACKEND (FastAPI + LangGraph)                         │
│                                                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    LangGraph StateGraph                          │   │
│   │                                                                  │   │
│   │   START ──▶ Planner ──▶ Approval ──▶ Executor ──▶ Summary ──▶ END│   │
│   │               │          (interrupt)      │                      │   │
│   │               │              │            ▼                      │   │
│   │               │              │      ┌──────────┐                 │   │
│   │               │              │      │ToolNode │                  │   │
│   │               │              │      │  (MCP)  │                  │   │
│   │               │              │      └──────────┘                 │   │
│   │               │              │                                   │   │
│   │   ┌───────────┴──────────────┴─────────────────────────────┐    │   │
│   │   │            AsyncMongoDBSaver (Checkpoints)              │    │   │
│   │   └─────────────────────────────────────────────────────────┘    │   │
│   └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │           langchain-mcp-adapters (MCP Client)                    │   │
│   │   MultiServerMCPClient → Loads MCP tools with auth headers      │   │
│   └──────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    MCP SERVER (FastMCP)                                  │
│                                                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │              BearerAuthProvider (JWT Validation)                 │   │
│   │   - Validates token signature                                    │   │
│   │   - Extracts user_id, role, permissions                         │   │
│   │   - Enforces RBAC on each tool call                             │   │
│   └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│   @mcp.tool()                                                            │
│   def create_item(ctx, name, description, data):                        │
│       if not ctx.user.has_scope("items:write"):                         │
│           raise Forbidden()                                             │
│       return backend_api.create_item(...)                               │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Multi-Agent Parallel Execution Deep Dive

### The Core Question: How Do 4 Agents Run in Parallel?

When you need to create 4 items (and don't have bulk_create), you need 4 parallel agents. Here's how different systems handle this:

### How Popular Agents Do It

#### 1. Claude (Anthropic) - Multi-Agent Research System

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     LEAD ORCHESTRATOR AGENT                               │
│                    (Claude Opus 4 - Planning)                             │
│                                                                           │
│   User Goal: "Create 4 items"                                            │
│              │                                                            │
│              ▼                                                            │
│   ┌─────────────────────────────────────────────────────────────────┐    │
│   │           DECOMPOSE INTO PARALLEL SUBTASKS                       │    │
│   │   Task 1: create_item("Alice")  │  Task 2: create_item("Bob")   │    │
│   │   Task 3: create_item("Carol")  │  Task 4: create_item("Dave")  │    │
│   └─────────────────────────────────────────────────────────────────┘    │
│                                │                                          │
│                                ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────┐    │
│   │              SPAWN 4 PARALLEL SUBAGENTS                          │    │
│   │   Each gets its OWN context window (isolated)                    │    │
│   │   Each can use tools independently                               │    │
│   │   All run CONCURRENTLY via asyncio                               │    │
│   └─────────────────────────────────────────────────────────────────┘    │
│                                │                                          │
│                                ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────┐    │
│   │              AGGREGATE RESULTS                                   │    │
│   │   Lead agent collects all 4 results                              │    │
│   │   Synthesizes into unified response                              │    │
│   └─────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key Insight**: Claude uses **asyncio concurrency** (not multiprocessing). Each subagent is an independent Claude instance with isolated context. They run in parallel via async/await.

#### 2. GitHub Copilot - `/fleet` Command

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    AGENTIC HARNESS (Orchestrator)                         │
│                                                                           │
│   /fleet "Create 4 items: Alice, Bob, Carol, Dave"                       │
│              │                                                            │
│              ▼                                                            │
│   ┌─────────────────────────────────────────────────────────────────┐    │
│   │           TASK DECOMPOSITION & DEPENDENCY ANALYSIS               │    │
│   │   • Identifies 4 independent subtasks (no dependencies)          │    │
│   │   • Routes each to specialized "Task" agent                      │    │
│   └─────────────────────────────────────────────────────────────────┘    │
│                                │                                          │
│                                ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────┐    │
│   │              PARALLEL AGENT SPAWN                                │    │
│   │                                                                  │    │
│   │   ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐               │    │
│   │   │Agent 1 │  │Agent 2 │  │Agent 3 │  │Agent 4 │               │    │
│   │   │(Sonnet)│  │(Haiku) │  │(Sonnet)│  │(GPT-5) │               │    │
│   │   │Alice   │  │Bob     │  │Carol   │  │Dave    │               │    │
│   │   └────────┘  └────────┘  └────────┘  └────────┘               │    │
│   │       │           │           │           │                     │    │
│   │       └───────────┴───────────┴───────────┘                     │    │
│   │                       │                                         │    │
│   │              asyncio.gather() / concurrent.futures              │    │
│   └─────────────────────────────────────────────────────────────────┘    │
│                                │                                          │
│                                ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────┐    │
│   │              AGENT HQ (Mission Control)                          │    │
│   │   • Real-time monitoring of all 4 agents                         │    │
│   │   • Can pause/resume individual agents                           │    │
│   │   • Aggregates results into unified PR                           │    │
│   └─────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key Insight**: GitHub Copilot can use **different LLM models** for different subagents (e.g., expensive Opus for planning, cheap Haiku for simple tasks).

### LangGraph Parallel Execution: The `Send()` Pattern

```python
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from typing import Annotated, TypedDict
import operator

class AgentState(TypedDict):
    goal: str
    items_to_create: list[dict]  # e.g., [{"name": "Alice"}, {"name": "Bob"}, ...]
    results: Annotated[list, operator.add]  # Reducer: merge results from parallel agents

# Fan-out: Dispatch to parallel workers
def dispatch_parallel_agents(state: AgentState) -> list[Send]:
    """Spawn one agent per item to create."""
    return [
        Send("create_item_agent", {"item": item, "token": state["token"]})
        for item in state["items_to_create"]
    ]

# Worker node: Each runs independently
async def create_item_agent(state: dict) -> dict:
    """Independent agent that creates one item."""
    item = state["item"]
    result = await mcp_client.call_tool("create_item", {
        "name": item["name"],
        "description": item.get("description", "")
    })
    return {"results": [result]}  # Returns to reducer

# Build graph
builder = StateGraph(AgentState)
builder.add_node("create_item_agent", create_item_agent)
builder.add_conditional_edges(START, dispatch_parallel_agents)
builder.add_edge("create_item_agent", END)

graph = builder.compile()

# Execute: All 4 agents run in parallel!
result = await graph.ainvoke({
    "goal": "Create 4 items",
    "items_to_create": [
        {"name": "Alice"}, {"name": "Bob"}, 
        {"name": "Carol"}, {"name": "Dave"}
    ],
    "token": user_token
})
# result["results"] = [item1, item2, item3, item4]
```

### Execution Model: Asyncio vs Multiprocessing

| Aspect | asyncio (Default) | ProcessPoolExecutor |
|--------|-------------------|---------------------|
| **Use Case** | I/O-bound (API calls, DB) | CPU-bound (ML inference) |
| **Our Case** | ✅ MCP tool calls are I/O | ❌ Not needed |
| **How** | Event loop concurrency | Separate OS processes |
| **GIL** | Single thread, blocked by CPU | Bypasses GIL |
| **Memory** | Shared memory | Isolated per process |

**For our use case (MCP tool calls)**: **asyncio is correct**. Making 4 HTTP calls to MCP server is I/O-bound, not CPU-bound.

```python
# LangGraph uses asyncio internally for parallel nodes
# This is equivalent to:
results = await asyncio.gather(
    create_item_agent({"item": {"name": "Alice"}}),
    create_item_agent({"item": {"name": "Bob"}}),
    create_item_agent({"item": {"name": "Carol"}}),
    create_item_agent({"item": {"name": "Dave"}}),
)
```

### When to Use ProcessPoolExecutor

If agents did **CPU-heavy work** (rare for MCP tools):

```python
from concurrent.futures import ProcessPoolExecutor
import asyncio

executor = ProcessPoolExecutor(max_workers=4)

async def cpu_heavy_agent(state: dict):
    """For CPU-bound work, offload to process pool."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        executor,
        heavy_computation,  # Runs in separate process
        state["data"]
    )
    return {"results": [result]}
```

### LangGraph Concurrency Control

```python
# Limit parallel agents to prevent overwhelming resources
graph = builder.compile(
    checkpointer=checkpointer,
    # Max 10 parallel agents at once (throttling)
    interrupt_before=["approval"],
)

# Or at runtime:
async for event in graph.astream(
    input_state,
    config={"max_concurrency": 4}  # Only 4 agents at a time
):
    yield event
```

### Summary: Multi-Agent Parallelism

| System | Parallelism Method | Orchestrator | Worker Isolation |
|--------|-------------------|--------------|------------------|
| **Claude** | asyncio + subagents | Lead Opus agent | Separate context windows |
| **GitHub Copilot** | asyncio + fleet | Agentic harness | Separate CLI instances |
| **LangGraph** | asyncio + `Send()` | StateGraph | Same process, isolated state |
| **Our Current** | `asyncio.gather()` | Custom orchestrator | Same process |

**Recommendation**: LangGraph's `Send()` pattern provides the same capability as Claude/Copilot with cleaner code.

---

## Current State Analysis

### What We Have (Custom Implementation)

Our current agent system has **significant custom code** that LangGraph provides out-of-the-box:

| Current Component | File | What It Does | LangGraph Equivalent |
|-------------------|------|--------------|---------------------|
| `MultiAgentOrchestrator` | `multi_agent.py` | Session management, execution flow | `StateGraph` + `checkpointer` |
| `generate_plan_streaming()` | `multi_agent.py` | AI plan generation | `create_react_agent` or custom nodes |
| `execute_plan_streaming()` | `multi_agent.py` | Sequential/parallel execution | Graph edges with `Send()` for parallel |
| `_execute_parallel_tasks_ai()` | `multi_agent.py` | Parallel task execution | Graph fan-out pattern |
| `_execute_sequential_tasks_ai()` | `multi_agent.py` | Sequential task execution | Linear graph edges |
| `MongoDBCheckpoint` | `mongodb_store.py` | Hot state storage | `AsyncMongoDBSaver` |
| `RedisCheckpoint` | `redis_store.py` | Cold state storage | `AsyncRedisSaver` |
| `AIService.execute_task()` | `ai_service.py` | LLM task execution | ReAct agent with tools |
| Custom SSE streaming | `agent_routes.py` | Real-time updates | `graph.astream()` |

### Problems with Current Approach

1. **~600 lines of custom orchestration** that LangGraph handles natively
2. **Manual state management** instead of automatic checkpointing
3. **No proper interrupts** - plan approval is hacked via separate endpoints
4. **Sequential execution in main thread** - no true parallelism
5. **Custom checkpoint format** - not compatible with LangGraph ecosystem
6. **No built-in replay/resume** - can't restart from checkpoint properly

---

## LangGraph Solution

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         LangGraph Agent                                  │
│                                                                          │
│   ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐          │
│   │ Router  │────▶│ Planner │────▶│Interrupt│────▶│Executor │          │
│   │  Node   │     │  Node   │     │  (HITL) │     │  Node   │          │
│   └─────────┘     └─────────┘     └─────────┘     └─────────┘          │
│        │                               │                │               │
│        │                          Human Approval        │               │
│        │                               │                ▼               │
│        │                               │         ┌─────────┐           │
│        │                               └────────▶│  Tools  │           │
│        │                                         │  (MCP)  │           │
│        │                                         └─────────┘           │
│        │                                               │               │
│        └───────────────────────────────────────────────┘               │
│                              │                                          │
│                    ┌─────────┴─────────┐                               │
│                    │   Checkpointer    │                               │
│                    │ (MongoDB + Redis) │                               │
│                    └───────────────────┘                               │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key LangGraph Features We'll Use

#### 1. **StateGraph with TypedDict**
```python
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    goal: str
    plan: list
    current_step: int
    results: list
    user_id: str
    token: str  # For MCP auth
```

#### 2. **AsyncMongoDBSaver for Checkpoints**
```python
from langgraph.checkpoint.mongodb.aio import AsyncMongoDBSaver
from motor.motor_asyncio import AsyncIOMotorClient

client = AsyncIOMotorClient(MONGODB_URL)
checkpointer = AsyncMongoDBSaver(client, "ai_experiments")
```

#### 3. **Human-in-the-Loop with Interrupts**
```python
from langgraph.types import interrupt, Command

def plan_approval_node(state: AgentState):
    """Pause for human approval of plan."""
    approval = interrupt({
        "type": "plan_approval",
        "plan": state["plan"],
        "message": "Review and approve the plan"
    })
    return {"approved": approval.get("approved", False)}
```

#### 4. **MCP Tool Integration**
```python
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp.client.sse import sse_client

async def load_tools(token: str):
    """Load MCP tools with auth token."""
    async with sse_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            # Wrap tools to inject token
            return [wrap_tool_with_auth(t, token) for t in tools]
```

#### 5. **Parallel Execution with Send()**
```python
from langgraph.constants import Send

def parallel_dispatcher(state: AgentState):
    """Fan out to parallel task nodes."""
    tasks = state["plan"][state["current_step"]].get("sub_tasks", [])
    return [Send("execute_task", {"task": task}) for task in tasks]
```

#### 6. **Streaming with astream()**
```python
# FastAPI SSE endpoint
async def stream_agent(goal: str, thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    async for event in graph.astream({"goal": goal}, config, stream_mode="messages"):
        yield f"data: {json.dumps(event)}\n\n"
```

---

## Migration Steps

### Phase 1: Setup LangGraph Infrastructure (Week 1)

1. **Add dependencies**
   ```
   langgraph>=0.2.0
   langgraph-checkpoint-mongodb>=0.2.0
   langchain-google-genai  # For Gemini
   langchain-mcp-adapters  # For MCP integration
   ```

2. **Create LangGraph state schema**
   - Define `AgentState` TypedDict
   - Define reducers for accumulating results

3. **Setup checkpointer**
   - Configure `AsyncMongoDBSaver`
   - Map existing checkpoint data to LangGraph format

### Phase 2: Build Core Graph (Week 1-2)

1. **Create graph nodes:**
   - `router_node`: Analyze goal, decide on approach
   - `planner_node`: Generate plan using LLM
   - `approval_node`: Human-in-the-loop interrupt
   - `executor_node`: Execute plan steps
   - `tool_node`: Call MCP tools
   - `summary_node`: Generate final summary

2. **Define edges:**
   ```python
   builder = StateGraph(AgentState)
   builder.add_node("router", router_node)
   builder.add_node("planner", planner_node)
   builder.add_node("approval", approval_node)
   builder.add_node("executor", executor_node)
   builder.add_node("tools", ToolNode(tools))
   builder.add_node("summary", summary_node)
   
   builder.add_edge(START, "router")
   builder.add_edge("router", "planner")
   builder.add_edge("planner", "approval")
   builder.add_conditional_edges("approval", check_approval, {
       "approved": "executor",
       "rejected": END
   })
   builder.add_conditional_edges("executor", should_continue, {
       "continue": "executor",
       "tools": "tools",
       "done": "summary"
   })
   builder.add_edge("tools", "executor")
   builder.add_edge("summary", END)
   ```

### Phase 3: MCP Integration (Week 2)

1. **Create MCP tool adapter**
   - Use `langchain-mcp-adapters` to load tools
   - Wrap tools to inject Bearer token for auth

2. **Handle authorization errors**
   - Tools return structured errors
   - Graph handles auth failures gracefully

### Phase 4: API Integration (Week 2-3)

1. **Update FastAPI endpoints**
   ```python
   @router.post("/sessions")
   async def create_session(goal: str, user: User):
       thread_id = str(uuid.uuid4())
       config = {"configurable": {"thread_id": thread_id}}
       # Start graph execution
       result = await graph.ainvoke({"goal": goal, "user_id": user.id}, config)
       return {"session_id": thread_id, "status": "planning"}
   
   @router.post("/sessions/{session_id}/approve")
   async def approve_plan(session_id: str, approved: bool):
       # Resume graph from interrupt
       config = {"configurable": {"thread_id": session_id}}
       await graph.ainvoke(Command(resume={"approved": approved}), config)
   
   @router.get("/sessions/{session_id}/stream")
   async def stream_session(session_id: str):
       config = {"configurable": {"thread_id": session_id}}
       async def generate():
           async for event in graph.astream(None, config, stream_mode="messages"):
               yield f"data: {json.dumps(event)}\n\n"
       return StreamingResponse(generate(), media_type="text/event-stream")
   ```

2. **Update frontend to handle new event format**

### Phase 5: Cleanup & Testing (Week 3)

1. **Remove deprecated code:**
   - `MultiAgentOrchestrator` class
   - Custom checkpoint stores
   - Manual state management

2. **Update tests**

3. **Documentation**

---

## Files to Change

### Delete (Custom → LangGraph)
- `app/agent/multi_agent.py` → Replace with `app/agent/graph.py`
- `app/checkpoints/mongodb_store.py` → Use `langgraph-checkpoint-mongodb`
- `app/checkpoints/redis_store.py` → Use `langgraph-checkpoint-redis`

### Modify
- `app/agent/ai_service.py` → Simplify to just LLM calls (no orchestration)
- `app/api/agent_routes.py` → Use LangGraph streaming
- `requirements.txt` → Add LangGraph packages

### New Files
- `app/agent/graph.py` → LangGraph StateGraph definition
- `app/agent/nodes.py` → Graph node implementations
- `app/agent/tools.py` → MCP tool loading and wrapping
- `app/agent/state.py` → TypedDict state definitions

---

## Benefits After Migration

| Aspect | Before | After |
|--------|--------|-------|
| **Lines of Code** | ~800 custom | ~200 (80% reduction) |
| **Checkpointing** | Custom MongoDB/Redis | Built-in, battle-tested |
| **Human-in-Loop** | Hacky endpoint | Native `interrupt()` |
| **Parallelism** | `asyncio.gather` | Graph `Send()` pattern |
| **Streaming** | Custom SSE | `graph.astream()` |
| **Resume** | Manual | Automatic from checkpoint |
| **Debugging** | Print statements | LangSmith integration |
| **Testing** | Hard to mock | Built-in test utilities |

---

## Example: Complete LangGraph Implementation

```python
# app/agent/graph.py
from typing import Annotated, TypedDict, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.mongodb.aio import AsyncMongoDBSaver
from langgraph.types import interrupt
from langchain_google_genai import ChatGoogleGenerativeAI

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    goal: str
    plan: list
    step_index: int
    results: list
    user_id: str
    token: str

# Nodes
async def planner_node(state: AgentState):
    """Generate plan using LLM."""
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")
    response = await llm.ainvoke([
        {"role": "system", "content": PLANNER_PROMPT},
        {"role": "user", "content": state["goal"]}
    ])
    plan = parse_plan(response.content)
    return {"plan": plan, "messages": [{"role": "assistant", "content": f"Plan: {plan}"}]}

async def approval_node(state: AgentState):
    """Wait for human approval."""
    result = interrupt({
        "type": "plan_approval",
        "plan": state["plan"]
    })
    return {"approved": result.get("approved", False)}

async def executor_node(state: AgentState):
    """Execute current step."""
    step = state["plan"][state["step_index"]]
    # ... execute step
    return {"step_index": state["step_index"] + 1, "results": [...]}

def should_continue(state: AgentState) -> Literal["executor", "done"]:
    if state["step_index"] < len(state["plan"]):
        return "executor"
    return "done"

# Build graph
builder = StateGraph(AgentState)
builder.add_node("planner", planner_node)
builder.add_node("approval", approval_node)
builder.add_node("executor", executor_node)

builder.add_edge(START, "planner")
builder.add_edge("planner", "approval")
builder.add_conditional_edges("approval", 
    lambda s: "executor" if s.get("approved") else "end",
    {"executor": "executor", "end": END}
)
builder.add_conditional_edges("executor", should_continue)
builder.add_edge("done", END)

# Compile with checkpointer
async def create_graph():
    client = AsyncIOMotorClient(MONGODB_URL)
    checkpointer = AsyncMongoDBSaver(client, "ai_experiments")
    return builder.compile(checkpointer=checkpointer)
```

---

## Comparison: Current vs LangGraph

### Current: Custom Sequential Execution
```python
# multi_agent.py - 100+ lines just for execution
async def execute_plan_streaming(self, session_id: str):
    session = self.sessions.get(session_id)
    for step_index, step in enumerate(session.plan):
        if step.get("execution_mode") == "parallel":
            async for update in self._execute_parallel_tasks_ai(...):
                yield update
        else:
            async for update in self._execute_sequential_tasks_ai(...):
                yield update
        await self._save_session_state(session)
    # ... more boilerplate
```

### LangGraph: Declarative Graph
```python
# graph.py - 20 lines for same functionality
builder = StateGraph(AgentState)
builder.add_node("executor", executor_node)
builder.add_conditional_edges("executor", should_continue, {
    "continue": "executor",
    "done": END
})
graph = builder.compile(checkpointer=checkpointer)

# Execution is automatic with streaming
async for event in graph.astream(input, config, stream_mode="messages"):
    yield event
```

---

## Implementation Status ✅ COMPLETED

The LangGraph migration has been implemented. See `docs/LANGGRAPH_IMPLEMENTATION.md` for the complete guide.

### New Files Created

| File | Purpose |
|------|---------|
| `app/agent/state.py` | AgentState TypedDict with reducers |
| `app/agent/nodes.py` | Graph nodes (planner, approval, executor, summary) |
| `app/agent/graph.py` | StateGraph with checkpointing |
| `app/agent/tools.py` | MCP tool wrapper |
| `docs/LANGGRAPH_IMPLEMENTATION.md` | Implementation guide |

### New API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/agent/v2/sessions` | POST | Create session, generate plan |
| `/agent/v2/sessions/{id}` | GET | Get session state |
| `/agent/v2/sessions/{id}/approve` | POST | Approve/reject plan |
| `/agent/v2/sessions/{id}/stream` | GET | SSE stream events |

### Dependencies Added

```
langgraph-checkpoint-mongodb>=2.0.0
langchain-mcp-adapters>=0.1.0
```

---

## References

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [AsyncMongoDBSaver](https://langchain-mongodb.readthedocs.io/en/stable/langgraph_checkpoint_mongodb/)
- [Human-in-the-Loop](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [MCP Integration](https://github.com/langchain-ai/langchain-mcp-adapters)
- [Parallel Execution](https://focused.io/lab/parallel-execution-with-langchain-and-langgraph)
- [FastAPI + LangGraph Streaming](https://dev.to/kasi_viswanath/streaming-ai-agent-with-fastapi-langgraph-2025-26-guide-1nkn)
- [LangGraph + MCP Example](https://github.com/teddynote-lab/langgraph-mcp-agents)
