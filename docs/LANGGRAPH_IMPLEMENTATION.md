# LangGraph Implementation Guide

## Overview

This document provides a comprehensive guide to the LangGraph-based multi-agent system implemented in this project. It covers architecture, parallel execution patterns, and how popular agent systems (Claude, GitHub Copilot) handle similar challenges.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Multi-Agent Parallelism Deep Dive](#multi-agent-parallelism-deep-dive)
3. [LangGraph Implementation](#langgraph-implementation)
4. [API Reference](#api-reference)
5. [Framework Comparison](#framework-comparison)
6. [Debugging & Monitoring](#debugging--monitoring)

---

## Architecture Overview

### System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React)                                 │
│   AgentPanel.jsx ─── EventSource for SSE streaming                      │
└────────────────────────────────────┬────────────────────────────────────┘
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
│   │           MCP Tool Wrapper (app/agent/tools.py)                  │   │
│   │   Loads tools from MCP server, injects auth tokens              │   │
│   └──────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    MCP SERVER (:8001)                                    │
│                                                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │              JWT Bearer Token Validation                         │   │
│   │   - Validates token signature                                    │   │
│   │   - Extracts user_id, role, permissions                         │   │
│   │   - Enforces RBAC on each tool call                             │   │
│   └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│   Tools: create_item, read_item, update_item, delete_item, etc.        │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| **State Schema** | `app/agent/state.py` | TypedDict with reducers for parallel execution |
| **Graph Nodes** | `app/agent/nodes.py` | Planner, Approval, Executor, Summary nodes |
| **StateGraph** | `app/agent/graph.py` | Graph builder with checkpointing |
| **MCP Tools** | `app/agent/tools.py` | Tool loading and execution wrapper |
| **API Routes** | `app/api/agent_routes.py` | REST endpoints for sessions |

---

## Multi-Agent Parallelism Deep Dive

### The Core Question: How Do 4 Agents Run in Parallel?

When you need to create 4 items (without bulk_create), you need 4 parallel agents. Here's how different systems handle this:

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

**Key Insight**: Claude uses **asyncio concurrency** (not multiprocessing). Each subagent is an independent Claude instance with isolated context.

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
└──────────────────────────────────────────────────────────────────────────┘
```

**Key Insight**: GitHub Copilot can use **different LLM models** for different subagents.

### Execution Model: Asyncio vs Multiprocessing

| Aspect | asyncio (Default) | ProcessPoolExecutor |
|--------|-------------------|---------------------|
| **Use Case** | I/O-bound (API calls, DB) | CPU-bound (ML inference) |
| **Our Case** | ✅ MCP tool calls are I/O | ❌ Not needed |
| **How** | Event loop concurrency | Separate OS processes |
| **GIL** | Single thread, blocked by CPU | Bypasses GIL |
| **Memory** | Shared memory | Isolated per process |

**For our use case (MCP tool calls)**: **asyncio is correct**. Making 4 HTTP calls to MCP server is I/O-bound.

---

## LangGraph Implementation

### State Schema (`app/agent/state.py`)

```python
from typing import TypedDict, Annotated, List
from operator import add

class AgentState(TypedDict, total=False):
    # Session metadata
    session_id: str
    user_id: str
    token: str  # JWT for MCP authorization
    
    # Goal and planning
    goal: str
    plan: List[PlanStep]
    current_step: int
    
    # Execution state - use reducers for parallel accumulation
    results: Annotated[List[TaskResult], add]  # <-- REDUCER!
    messages: Annotated[List[Dict], add]       # <-- REDUCER!
    
    # Status tracking
    status: Literal["initialized", "planning", "awaiting_approval", "executing", "completed", "failed"]
    approved: bool
    error: Optional[str]
    summary: Optional[Dict[str, Any]]
```

**Important**: The `Annotated[List, add]` pattern creates a **reducer** that merges results from parallel branches.

### Parallel Execution with `Send()` (`app/agent/nodes.py`)

```python
from langgraph.types import Send

def executor_dispatch(state: AgentState) -> List[Send]:
    """Fan-out to parallel task execution."""
    step = state["plan"][state["current_step"]]
    sub_tasks = step.get("sub_tasks", [])
    
    # Create Send() for each task - they run in PARALLEL
    return [
        Send("task_executor", {
            "session_id": state["session_id"],
            "token": state["token"],
            "task": task
        })
        for task in sub_tasks
    ]
```

### Human-in-the-Loop with `interrupt()` (`app/agent/nodes.py`)

```python
from langgraph.types import interrupt

def approval_node(state: AgentState) -> Dict[str, Any]:
    """Pause for human approval."""
    approval_response = interrupt({
        "type": "plan_approval",
        "plan": state.get("plan", []),
        "message": "Please review and approve the execution plan"
    })
    
    return {"approved": approval_response.get("approved", False)}
```

### Graph Building (`app/agent/graph.py`)

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.mongodb.aio import AsyncMongoDBSaver

builder = StateGraph(AgentState)

# Add nodes
builder.add_node("planner", planner_node)
builder.add_node("approval", approval_node)
builder.add_node("task_executor", task_executor_node)
builder.add_node("aggregator", step_aggregator_node)
builder.add_node("summary", summary_node)

# Add edges
builder.add_edge(START, "planner")
builder.add_edge("planner", "approval")
builder.add_conditional_edges("approval", check_approval, {...})
builder.add_conditional_edges("executor_dispatch", executor_dispatch)  # Fan-out
builder.add_edge("task_executor", "aggregator")
builder.add_conditional_edges("aggregator", should_continue, {...})
builder.add_edge("summary", END)

# Compile with checkpointer
graph = builder.compile(
    checkpointer=AsyncMongoDBSaver(mongo_client, "ai_experiments"),
    interrupt_before=["approval"]  # HITL pause point
)
```

---

## API Reference

### V2 Endpoints (LangGraph-based)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/agent/v2/sessions` | POST | Create session, generate plan |
| `/agent/v2/sessions/{id}` | GET | Get session state |
| `/agent/v2/sessions/{id}/approve` | POST | Approve/reject plan |
| `/agent/v2/sessions/{id}/stream` | GET | SSE stream events |

### Example Flow

```bash
# 1. Create session and generate plan
curl -X POST http://localhost:8000/agent/v2/sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"goal": "Create 4 items: Alice, Bob, Carol, Dave"}'

# Response:
# {
#   "session_id": "abc-123",
#   "status": "awaiting_approval",
#   "plan": [...]
# }

# 2. Approve the plan
curl -X POST http://localhost:8000/agent/v2/sessions/abc-123/approve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"approved": true}'

# 3. Stream execution events
curl -N http://localhost:8000/agent/v2/sessions/abc-123/stream \
  -H "Authorization: Bearer $TOKEN"

# data: {"type": "task_complete", "task": "Create Alice", "status": "success"}
# data: {"type": "task_complete", "task": "Create Bob", "status": "success"}
# data: {"type": "execution_complete", "summary": {...}}
```

---

## Framework Comparison

### Agent Orchestration Frameworks

| Framework | Architecture | Best For | MCP Support |
|-----------|-------------|----------|-------------|
| **LangGraph** ⭐ | Graph-based state machines | Complex workflows with HITL | Via langchain-mcp-adapters |
| **CrewAI** | Role-based teams | Simple pipelines | Manual |
| **Agno** (NEW) | Modern Python + AgentOS | Quick deployment with UI | **Native MCPTools** |
| **AutoGen** | Multi-agent conversation | Research | Manual |

### MCP Frameworks

| Framework | Language | Auth Support | Use Case |
|-----------|----------|--------------|----------|
| **FastMCP** ⭐ | Python | JWT, OAuth2.1, API Key | Server with built-in auth |
| **mcp-framework** | TypeScript | OAuth2.1, JWT, API Key | Node.js ecosystems |
| **langchain-mcp-adapters** ⭐ | Python | Header injection | Client for LangGraph |

### Decision Matrix

| Requirement | LangGraph | CrewAI | Agno |
|-------------|-----------|--------|------|
| Human-in-the-loop | ✅ Native `interrupt()` | ⚠️ Manual | ✅ Approval flows |
| MongoDB checkpoints | ✅ `AsyncMongoDBSaver` | ❌ Custom needed | ✅ Built-in |
| MCP integration | ✅ `langchain-mcp-adapters` | ⚠️ Manual | ✅ Native `MCPTools` |
| Parallel execution | ✅ `Send()` pattern | ✅ Parallel tasks | ✅ Async |
| SSE streaming | ✅ `astream()` | ⚠️ Custom | ✅ Built-in |

**Winner: LangGraph** - Best fit for our requirements.

---

## Debugging & Monitoring

### Logging Prefixes

All AI-related logs use `[AIFLOW]` prefix for easy filtering:

```bash
# Filter AI flow logs
docker logs ai-experiments-app-1 | grep "\[AIFLOW\]"

# Example output:
# [AIFLOW] AI Prompt: You are a planning agent...
# [AIFLOW] AI Response: {"analysis": "...", "steps": [...]}
# [AIFLOW] MCP Tool Called: create_item with params: {"name": "Alice"}
# [AIFLOW] MCP Tool Result: create_item -> {"id": "123", "name": "Alice"}
```

### Checkpoint Inspection

```python
# Get checkpoint from MongoDB
from langgraph.checkpoint.mongodb.aio import AsyncMongoDBSaver

async def inspect_checkpoint(session_id: str):
    client = AsyncIOMotorClient(MONGODB_URL)
    checkpointer = AsyncMongoDBSaver(client, "ai_experiments")
    
    config = {"configurable": {"thread_id": session_id}}
    state = await graph.aget_state(config)
    
    print(f"Status: {state.values.get('status')}")
    print(f"Current Step: {state.values.get('current_step')}")
    print(f"Results: {len(state.values.get('results', []))}")
```

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Plan not generated | AI service not initialized | Check Vertex AI credentials |
| Authorization failed | Invalid/expired token | Generate new MCP token |
| Parallel tasks sequential | Missing `Send()` return | Ensure executor returns `List[Send]` |
| Checkpoints not saved | MongoDB connection | Verify MONGODB_URL |

---

## File Structure

```
app/agent/
├── __init__.py
├── state.py          # AgentState TypedDict with reducers
├── nodes.py          # Graph nodes (planner, approval, executor, summary)
├── graph.py          # StateGraph builder with checkpointing
├── tools.py          # MCP tool wrapper
├── ai_service.py     # Vertex AI integration
├── multi_agent.py    # Legacy orchestrator (kept for compatibility)
└── langgraph_agent.py # Legacy plan mode agent
```

---

## References

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [AsyncMongoDBSaver](https://langchain-mongodb.readthedocs.io/en/stable/langgraph_checkpoint_mongodb/)
- [Human-in-the-Loop](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [MCP Integration](https://github.com/langchain-ai/langchain-mcp-adapters)
- [Anthropic Multi-Agent Research](https://www.anthropic.com/engineering/multi-agent-research-system)
- [GitHub Copilot Fleet](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/fleet)
