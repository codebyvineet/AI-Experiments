# LangGraph Migration Plan

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

## References

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [AsyncMongoDBSaver](https://langchain-mongodb.readthedocs.io/en/stable/langgraph_checkpoint_mongodb/)
- [Human-in-the-Loop](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [MCP Integration](https://github.com/langchain-ai/langchain-mcp-adapters)
- [Parallel Execution](https://focused.io/lab/parallel-execution-with-langchain-and-langgraph)
- [FastAPI + LangGraph Streaming](https://dev.to/kasi_viswanath/streaming-ai-agent-with-fastapi-langgraph-2025-26-guide-1nkn)
- [LangGraph + MCP Example](https://github.com/teddynote-lab/langgraph-mcp-agents)
