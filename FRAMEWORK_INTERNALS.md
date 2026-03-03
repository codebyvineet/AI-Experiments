# Framework Internals: LangGraph + Google ADK Deep Dive

This document covers the internal mechanics of both frameworks used in this project — how messages are stored, how state flows, how tools get wired in, and what the framework does (or doesn't do) for you at runtime.

---

## Table of Contents

1. [Message Storage Format](#1-message-storage-format)
2. [Retrieving History from the Database](#2-retrieving-history-from-the-database)
3. [What the Framework Handles for You](#3-what-the-framework-handles-for-you)
4. [Creating a Simple Agent](#4-creating-a-simple-agent)
5. [How Tools Are Provided: Chat vs Plan vs Execute](#5-how-tools-are-provided-chat-vs-plan-vs-execute)
6. [How State Is Saved (Checkpointing)](#6-how-state-is-saved-checkpointing)
7. [Saving Custom State at Any Point](#7-saving-custom-state-at-any-point)
8. [What Requests Are Streamable](#8-what-requests-are-streamable)
9. [SSE Stream Lifecycle](#85-sse-stream-lifecycle)
10. [Concurrent Input: What Happens When AI Is Running](#9-concurrent-input-what-happens-when-ai-is-running)
11. [LangGraph vs Google ADK Side-by-Side](#10-langgraph-vs-google-adk-side-by-side)

---

## 1. Message Storage Format

### LangGraph (Chat Mode + Plan Mode)

LangGraph persists state as **msgpack-serialised blobs** in two MongoDB collections:

| Collection | Purpose |
|---|---|
| `checkpoints` | Full state snapshot per graph execution step |
| `checkpoint_writes` | Incremental writes (partial state patches between checkpoints) |

**Document structure in `checkpoints`:**

```json
{
  "thread_id": "chat-69a6a37f753599c296370f42",
  "checkpoint_ns": "",
  "checkpoint_id": "1f116f12-abc1-...",
  "type": "msgpack",
  "checkpoint": "<binary msgpack>",
  "metadata": "<binary msgpack>"
}
```

> **Why not just JSON?** msgpack does the same job — serialize → store → deserialize. The real difference is LangGraph ships a msgpack codec that already knows how to serialize `HumanMessage`, `AIMessage`, `ToolMessage`, etc. You *could* use JSON, but you'd have to write the encoder/decoder for every LangChain message type yourself. msgpack is just the binary format LangGraph chose to build their pre-built codec on top of.

Once deserialised by `MongoDBSaver.get()`, the checkpoint is a plain Python dict:

```python
{
  "v": 4,
  "ts": "2026-03-03T11:07:28.509527+00:00",
  "id": "1f116f12-...",
  "channel_values": {
    "messages": [
      HumanMessage(content="how many items are there?"),
      AIMessage(content="", tool_calls=[{"name": "list_items", "args": {"limit": 0}}]),
      ToolMessage(content=[{"type": "text", "text": "{...items json...}"}], name="list_items"),
      AIMessage(content=[{"type": "text", "text": "There are 2 items in total."}])
    ]
  },
  "channel_versions": {...},
  "versions_seen": {...}
}
```

**Message types inside `channel_values.messages`:**

| Type | Class | When created |
|---|---|---|
| `"human"` | `HumanMessage` | Every user message sent to the agent |
| `"ai"` (with `tool_calls`) | `AIMessage` | LLM decided to call a tool — contains tool name + args |
| `"ai"` (no `tool_calls`) | `AIMessage` | LLM produced a final text answer |
| `"tool"` | `ToolMessage` | MCP tool execution result — linked to AIMessage via `tool_call_id` |

**Thread ID conventions:**

| Mode | Thread ID format |
|---|---|
| Chat (per user, persistent) | `chat-{user_id}` — same thread accumulates all chat history |
| Plan session (per session) | `{uuid}` — new UUID per goal, isolated from other sessions |

> **Who creates the thread?** Nobody explicitly — `thread_id` is just a string. The first time LangGraph writes a checkpoint with a given `thread_id`, MongoDB creates the document automatically. There is no "create thread" API call.
> - Chat: `thread_id = f"chat-{user_id}"` constructed in `react_agent.py` before calling `agent.astream()`
> - Plan: `session_id = str(uuid.uuid4())` in `graph.py`, used directly as `thread_id` in the graph config

**Important quirk — Gemini content format:**
Gemini returns `AIMessage.content` as a **list of blocks**, not a plain string:
```python
# Gemini format:
content = [{"type": "text", "text": "There are 2 items in total.", "thought_signature": "..."}]

# OpenAI/Anthropic format:
content = "There are 2 items in total."
```
Always use `_extract_text_content()` from `react_agent.py` to handle both cases.

---

### Google ADK (google-adk folder)

ADK does **not** persist conversation messages to MongoDB. It uses `InMemorySessionService` for conversation state, and only writes lightweight session **metadata** to the `agent_sessions` collection.

**`agent_sessions` document structure:**

```json
{
  "session_id": "uuid-...",
  "user_id": "user_demo",
  "is_planning_mode": true,
  "plan": [
    {"step_id": "1", "description": "List all items", "action": "list_items", "status": "completed", "result": {"text": "..."}},
    {"step_id": "2", "description": "Create a new item", "action": "create_item", "status": "pending"}
  ],
  "current_step": 1,
  "is_complete": false,
  "archived": false,
  "created_at": "2026-03-03T09:00:00Z",
  "updated_at": "2026-03-03T09:05:00Z"
}
```

The actual conversation turn history (what the model said, what tools it called) lives only in `InMemorySessionService` — it is **lost on server restart**.

---

## 2. Retrieving History from the Database

### LangGraph — Two ways

**Option A: Via the checkpointer directly (synchronous)**

```python
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
checkpointer = MongoDBSaver(client, db_name="mcp_demo")

config = {"configurable": {"thread_id": "chat-<user_id>", "checkpoint_ns": ""}}

# Returns the Checkpoint dict directly (NOT a CheckpointTuple)
checkpoint = checkpointer.get(config)

# Access messages:
messages = checkpoint["channel_values"]["messages"]
for msg in messages:
    print(msg.type, msg.content)
```

> **Note:** `MongoDBSaver.get()` is **synchronous**. In an async FastAPI handler, run it in an executor:
> ```python
> checkpoint = await asyncio.get_event_loop().run_in_executor(
>     None, lambda: checkpointer.get(config)
> )
> ```

**Option B: Via the compiled graph (async, preferred in graph context)**

```python
config = {"configurable": {"thread_id": session_id}}
state = await graph.aget_state(config)

# state.values is the full AgentState dict
messages = state.values.get("messages", [])
plan     = state.values.get("plan", [])
status   = state.values.get("status")

# Metadata about pending nodes
state.next    # tuple of next nodes to execute
state.tasks   # pending interrupt tasks
```

**Option C: Raw MongoDB query (for listing all sessions)**

```python
db = mongo_client["mcp_demo"]

# Get all thread_ids (each thread = one session or chat thread)
thread_ids = db.checkpoints.distinct("thread_id")

# Get latest checkpoint for a specific thread
latest = db.checkpoints.find_one(
    {"thread_id": "chat-<user_id>"},
    sort=[("checkpoint_id", -1)]
)
```

---

### Google ADK

```python
# Via the ADK manager (API-level access)
meta = await adk_agent._load_session_meta(session_id)
# Returns the agent_sessions document

# Raw MongoDB query
doc = await db.agent_sessions.find_one({"session_id": session_id})

# ADK session state (in-memory only — won't survive restart)
session = await adk_agent._session_service.get_session(
    app_name="adk_demo",
    user_id=user_id,
    session_id=session_id
)
# session.state = {"is_planning_mode": ..., "plan": [...], ...}
```

---

## 3. What the Framework Handles for You

### LangGraph

| Feature | What the framework does |
|---|---|
| **ReAct loop** | `create_react_agent` runs think → tool_call → observe → respond automatically until the LLM stops issuing tool calls |
| **Tool invocation** | Calls `tool.ainvoke(args)` for each `tool_call` in the AI message, injects `ToolMessage` back into history |
| **Checkpointing** | After every node execution, automatically serialises full state to MongoDB via `MongoDBSaver` |
| **Parallel execution** | `Send()` in conditional edges fans out to multiple `task_executor` nodes concurrently |
| **Human-in-the-loop** | `interrupt()` in a node pauses the graph; `Command(resume=...)` resumes it |
| **State reducers** | Fields annotated `Annotated[List, add]` are automatically merged when parallel branches rejoin |
| **Graph compilation** | `builder.compile(checkpointer=..., interrupt_before=[...])` wires everything together |
| **Streaming** | `graph.astream(stream_mode="updates")` yields `{node_name: node_output}` after each node |
| **Re-entrant execution** | Calling `graph.ainvoke(Command(resume=...), config)` seamlessly resumes from any checkpoint |

### Google ADK

| Feature | What the framework does |
|---|---|
| **ReAct loop** | `Runner.run_async()` handles the full think → call tool → observe → respond loop |
| **Tool invocation** | `MCPToolset` connects to MCP server and invokes tools transparently |
| **Session management** | `InMemorySessionService` tracks conversation turns per `(app_name, user_id, session_id)` |
| **Event streaming** | `run_async()` is an async generator that yields `Event` objects as the agent acts |
| **Multi-turn memory** | Conversation history is automatically appended within a session |

---

## 4. Creating a Simple Agent

### LangGraph — Minimal ReAct Agent (Chat Mode)

```python
from langchain_google_vertexai import ChatVertexAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.mongodb import MongoDBSaver
from langchain_mcp_adapters.client import MultiServerMCPClient
from pymongo import MongoClient

# 1. LLM
model = ChatVertexAI(model_name="gemini-2.5-pro", project="my-project", location="us-central1")

# 2. Tools (MCP)
mcp = MultiServerMCPClient({"main": {"transport": "streamable_http", "url": "http://mcp-server:8001/mcp", "headers": {"Authorization": "Bearer <token>"}}})
tools = await mcp.get_tools()

# 3. Checkpointer (persists conversation across turns)
checkpointer = MongoDBSaver(MongoClient("mongodb://localhost:27017"), db_name="mcp_demo")

# 4. Agent
agent = create_react_agent(
    model,
    tools,
    prompt="You are a helpful assistant. Use tools to answer questions.",
    checkpointer=checkpointer,
)

# 5. Stream
async for chunk in agent.astream(
    {"messages": [("user", "how many items are there?")]},
    stream_mode="updates",
    config={"configurable": {"thread_id": "chat-user123"}, "recursion_limit": 25},
):
    for node_name, output in chunk.items():
        for msg in output.get("messages", []):
            print(msg.type, msg.content)
```

The framework handles **all of**: tool selection, tool invocation, looping back if more tools are needed, and writing the final answer. The `thread_id` in config is what ties conversation turns together.

---

### LangGraph — Custom StateGraph (Plan Mode)

```python
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Send

builder = StateGraph(AgentState)
builder.add_node("planner", planner_node)
builder.add_node("approval", approval_node)          # Uses interrupt()
builder.add_node("executor_dispatch", executor_dispatch)
builder.add_node("task_executor", task_executor_node) # Called N times via Send()
builder.add_node("aggregator", step_aggregator_node)
builder.add_node("summary", summary_node)

builder.add_edge(START, "planner")
builder.add_edge("planner", "approval")
builder.add_conditional_edges("approval", check_approval, {"executor": "executor_dispatch", "summary": "summary"})
builder.add_conditional_edges("executor_dispatch", create_task_sends)  # Returns List[Send]
builder.add_edge("task_executor", "aggregator")
builder.add_conditional_edges("aggregator", should_continue, {"executor": "executor_dispatch", "summary": "summary"})
builder.add_edge("summary", END)

graph = builder.compile(
    checkpointer=MongoDBSaver(...),
    interrupt_before=["approval"]   # Pauses here waiting for human input
)
```

---

### Google ADK — Minimal Agent

```python
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

# 1. Tools
toolset = MCPToolset(connection_params=StreamableHTTPConnectionParams(url="http://mcp-server:8001/mcp"))

# 2. Agent
agent = LlmAgent(
    model="gemini-2.5-pro",
    name="my_agent",
    instruction="You are a helpful assistant. Use tools when needed.",
    tools=[toolset],
)

# 3. Runner + session
session_service = InMemorySessionService()
runner = Runner(agent=agent, app_name="my_app", session_service=session_service)
await session_service.create_session(app_name="my_app", user_id="user1", session_id="s1")

# 4. Run
from google.genai.types import Content, Part
async for event in runner.run_async(
    user_id="user1",
    session_id="s1",
    new_message=Content(role="user", parts=[Part.from_text("how many items?")])
):
    if event.content:
        for part in event.content.parts:
            if hasattr(part, "text") and part.text:
                print("TEXT:", part.text)
            elif hasattr(part, "function_call") and part.function_call:
                print("TOOL CALL:", part.function_call.name)
```

---

## 5. How Tools Are Provided: Chat vs Plan vs Execute

### Chat Mode (LangGraph `create_react_agent`)

```
User message
     │
     ▼
create_react_agent(model, tools, checkpointer=...)
     │
     ├─── agent node: LLM reasons, emits tool_calls
     │
     ├─── tools node: Framework calls tool.ainvoke(args) for each tool_call
     │
     └─── loops until LLM emits a text answer (no more tool_calls)
```

- Tools are **LangChain tool objects** returned by `mcp.get_tools()`
- Each tool is a `StructuredTool` wrapping an MCP JSON-RPC call
- The `MultiServerMCPClient` adds an `Authorization: Bearer <token>` header on every call
- Tools are bound to the model at agent creation time — the LLM sees their names and schemas in the system prompt automatically
- The framework loops indefinitely (up to `recursion_limit`) calling tools until the LLM stops

**Token source:** A short-lived MCP token is generated per request in `streaming.py`:
```python
mcp_token = await create_mcp_token(current_user)
```
This token embeds user permissions and is forwarded to the MCP server on every tool call.

---

### Plan Mode — Planning Phase (AI generates plan, no tools called)

```
POST /stream/sessions  →  create_session_id() stores pending state
GET  /sessions/{id}/plan  →  stream_graph() starts the graph
     │
     ▼
planner_node:
  ai_service.generate_plan(goal)
    └── ChatVertexAI.with_structured_output(PlanSchema)
        Returns: List[PlanStep] with tool names declared, NOT called
     │
     ▼
approval_node: interrupt() — graph pauses here
```

During planning, **no MCP tools are invoked**. The AI reasons about which tools it *would* call and generates a declarative plan. Each `PlanStep` contains:

```python
{
  "step_id": "step-0",
  "description": "List all current items",
  "mcp_tools_used": ["list_items"],
  "sub_tasks": [{"name": "List items", "tool": "list_items", "tool_params": {}}],
  "execution_mode": "sequential"
}
```

---

### Execute Mode (Plan Mode — Execution Phase)

```
GET /sessions/{id}/execute  →  stream_session(approve=True)
     │
     ▼
Command(resume={"approved": True})  — resumes past interrupt
     │
     ▼
executor_dispatch → create_task_sends() → List[Send("task_executor", task_state)]
     │                                        │
     │                                        └─── task_executor_node (N parallel instances)
     │                                              call_mcp_tool(tool_name, params, token)
     │
     ▼
aggregator_node → advances current_step
     │
     ▼
loops back to executor_dispatch for next step
```

In execution mode:
- Tools are called via `call_mcp_tool()` in `app/mcp/client.py`
- Each task gets its own MCP call with the JWT token from `AgentState.token`
- Parallel tasks run as separate `task_executor` node instances via `Send()`
- Authorization failures (`PermissionError`) are caught per task and tracked as `status: "authorization_failed"`

---

### Google ADK — Chat Mode

ADK wires tools differently — the `MCPToolset` is attached to the `LlmAgent` at construction time:

```python
agent = LlmAgent(
    model="gemini-2.5-pro",
    tools=[MCPToolset(connection_params=...)]   # <-- tools bound at construction
)
```

During `runner.run_async()`, the framework:
1. Sends the user message + tool schemas to Gemini
2. Gemini responds with a `function_call` part
3. ADK calls the MCP tool automatically
4. Returns a `function_response` part to Gemini
5. Gemini produces the final text answer

**Token limitation in ADK:** The MCP token cannot be injected into the `MCPToolset` at runtime — so the current implementation passes `auth_token` as a text string inside the user message, and the model is instructed to include it in every tool call argument. This is a workaround; the LangGraph approach (per-request token in `MultiServerMCPClient` headers) is cleaner.

---

### Google ADK — Plan Mode

ADK uses two separate agents:

| Agent | Role | Tools |
|---|---|---|
| `planner_agent` | Generates JSON plan (pure reasoning) | None |
| `chat_agent` (reused as executor) | Executes each step using MCP tools | MCPToolset |

Steps execute **sequentially** (unlike LangGraph which can fan out in parallel with `Send()`).

---

## 6. How State Is Saved (Checkpointing)

### LangGraph — Automatic

Every time a node completes, LangGraph automatically:
1. Serialises the full `AgentState` to msgpack
2. Writes it to MongoDB `checkpoints` with the current `thread_id` and a monotonically increasing `checkpoint_id`
3. Writes incremental patches to `checkpoint_writes`

This happens with **zero application code** — it is entirely driven by the `MongoDBSaver` passed to `builder.compile()`.

```
Node executes → returns state dict patch → LangGraph merges reducers → writes checkpoint
```

**What gets checkpointed:**
- Everything in `AgentState`: `goal`, `plan`, `current_step`, `results`, `messages`, `status`, `token`, etc.
- The checkpoint includes enough information to resume the graph from exactly that point

**State reducers** control how values merge when parallel branches write to the same field:

```python
class AgentState(TypedDict, total=False):
    results:  Annotated[List[TaskResult], add]  # append — parallel tasks each add their result
    messages: Annotated[List[Dict], add]        # append — each node adds to the log
    plan:     List[PlanStep]                    # replace — last write wins
    current_step: int                           # replace — last write wins
```

### Google ADK — Split

ADK splits persistence responsibility:

| What | Where |
|---|---|
| Conversation turns (messages, tool calls) | `InMemorySessionService` — RAM only |
| Session metadata (plan, step, completion) | MongoDB `agent_sessions` — explicit `update_one()` calls |

The application code is responsible for calling `_update_session_meta()` at the right time. If the process restarts, the conversation history is gone, but the plan and step counter survive.

---

## 7. Saving Custom State at Any Point

### LangGraph — `aupdate_state()`

You can inject arbitrary state into a running or paused LangGraph session without resuming the full graph:

```python
config = {"configurable": {"thread_id": session_id}}

await graph.aupdate_state(
    config,
    {
        "goal": "updated goal text",           # Change the goal
        "status": "replanning",                # Override status
        "approved": False,                     # Reset approval
        "current_step": 0,                     # Reset step counter
        "messages": existing + [new_message],  # Append to messages
    },
    as_node="planner"   # Pretend this update came from the planner node
                        # This determines which node runs next
)
```

**The `as_node` parameter is critical** — it tells LangGraph which node "wrote" this state, which determines what node runs next based on the graph edges. Common values:

| `as_node` | Next node after update |
|---|---|
| `"planner"` | `"approval"` (and re-pauses at interrupt) |
| `"executor_dispatch"` | Fan-out to `task_executor` nodes |
| `"summary"` | `END` |

**Use cases in this project:**

```python
# Interrupt and replan with new user input
await graph.aupdate_state(config, {"goal": new_input, "status": "replanning", "approved": False}, as_node="planner")

# Stop execution gracefully
await graph.aupdate_state(config, {"status": "stopped"})

# Retry from executor (skipping already-completed steps)
await graph.aupdate_state(config, {"status": "executing", "approved": True, "token": fresh_token}, as_node="executor_dispatch")

# User edited the plan
await graph.aupdate_state(config, {"plan": modified_plan}, as_node="planner")
```

### Google ADK — Direct MongoDB write

There is no equivalent to `aupdate_state` in ADK. You write directly to MongoDB:

```python
await db.agent_sessions.update_one(
    {"session_id": session_id},
    {"$set": {"plan": updated_plan, "current_step": 2, "updated_at": datetime.utcnow()}}
)
```

For in-memory session state:
```python
session = await session_service.get_session(app_name=..., user_id=..., session_id=...)
session.state["is_planning_mode"] = True
session.state["custom_key"] = "custom_value"
# No explicit save needed — InMemorySessionService holds the reference
```

---

## 8. What Requests Are Streamable

All streaming uses **Server-Sent Events (SSE)** via FastAPI `StreamingResponse` with `media_type="text/event-stream"`.

Each event is a JSON line prefixed `data: `:
```
data: {"type": "thinking", "message": "Connecting to MCP tools..."}\n\n
data: {"type": "tool_call", "tool": "list_items", "args": {"limit": 10}}\n\n
data: {"type": "tool_result", "tool": "list_items", "result": "{...}"}\n\n
data: {"type": "response", "message": "There are 2 items in total."}\n\n
```

### Streamable endpoints

| Endpoint | What streams |
|---|---|
| `POST /stream/chat` | `thinking` → `tool_call` → `tool_result` → `response` |
| `GET /stream/sessions/{id}/plan` | `status` → `thinking` → `plan_step` (×N) → `plan_complete` |
| `GET /stream/sessions/{id}/execute` | `status` → `step_start` → `task_complete` (×N) → `execution_complete` |

### Non-streamable (regular JSON responses)

| Endpoint | Returns |
|---|---|
| `POST /stream/sessions` | `{session_id, goal, status, plan}` — creates session, returns immediately |
| `GET /stream/sessions/{id}` | Full session state snapshot |
| `GET /stream/sessions` | List of user's sessions |
| `PUT /stream/sessions/{id}/plan` | Confirmation of plan update |
| `POST /stream/sessions/{id}/stop` | Stop confirmation + partial results |
| `POST /stream/sessions/{id}/resume` | Resume info + action needed |
| `POST /stream/sessions/{id}/message` | Re-plan confirmation |
| `GET /stream/chat/history` | All past messages for current user |

### Streaming internals

**The `event_generator` wrapper** in `streaming.py` is a thin adapter that converts any async generator to SSE format and handles disconnects:

```python
async def event_generator(events):
    try:
        async for event in events:
            yield f"data: {json.dumps(event)}\n\n"
    except asyncio.CancelledError:
        yield f"data: {json.dumps({'type': 'cancelled'})}\n\n"
```

**LangGraph `astream` modes** used:

| Mode | Used for | What each chunk contains |
|---|---|---|
| `"updates"` | Plan streaming, Chat mode | `{node_name: {state_fields_that_changed}}` |
| `"values"` | Execute mode | Full state snapshot after each node |

---

## 8.5. SSE Stream Lifecycle

### Request types per mode

**Chat mode** — one HTTP request, one stream, one close:

```
Client                                  FastAPI                              LangGraph
  │                                        │                                     │
  │  POST /stream/chat                     │                                     │
  │  {"message": "how many items?"}        │                                     │
  │ ─────────────────────────────────────► │                                     │
  │                                        │  agent.astream(...)                 │
  │                                        │ ──────────────────────────────────► │
  │  HTTP 200 text/event-stream opens      │                                     │
  │ ◄─────────────────────────────────── ──│                                     │
  │                                        │  ◄── {agent: {messages: [AIMessage(tool_calls)]}}
  │ ◄── data: {"type":"tool_call",...}      │                                     │
  │                                        │  ◄── {tools: {messages: [ToolMessage]}}
  │ ◄── data: {"type":"tool_result",...}   │                                     │
  │                                        │  ◄── {agent: {messages: [AIMessage(text)]}}
  │ ◄── data: {"type":"response",...}      │                                     │
  │                                        │  generator exhausted                │
  │  HTTP connection closes                │                                     │
  │ ◄─────────────────────────────────── ──│                                     │
```

**Plan mode** — two separate HTTP requests, two separate streams:

```
Client                         FastAPI                    LangGraph graph
  │                               │                            │
  │  POST /stream/sessions        │                            │
  │  {"goal": "..."}              │                            │
  │ ────────────────────────────► │  creates session_id        │
  │ ◄── 200 {session_id, ...}     │  (no stream yet)           │
  │                               │                            │
  │  GET /sessions/{id}/plan      │                            │
  │ ────────────────────────────► │  graph.astream(initial)   │
  │                               │ ─────────────────────────► │
  │  Stream 1 opens               │                            │  planner node runs
  │ ◄── data: {"type":"status"..} │ ◄── {planner: {...}}       │
  │ ◄── data: {"type":"plan_step"}│ ◄── {planner: {...}}  ×N   │
  │ ◄── data: {"type":"plan_complete"} │                       │  approval node: interrupt()
  │  Stream 1 closes (graph paused at interrupt)               │  ← graph paused here
  │                               │                            │
  │  [user reviews plan]          │                            │
  │                               │                            │
  │  GET /sessions/{id}/execute   │                            │
  │ ────────────────────────────► │  graph.astream(           │
  │                               │    Command(resume=True))  │
  │                               │ ─────────────────────────► │  resumes past interrupt
  │  Stream 2 opens               │                            │  executor runs tasks
  │ ◄── data: {"type":"step_start"}     ◄── {executor: {...}}  │
  │ ◄── data: {"type":"task_complete"}  ◄── {aggregator: {..}} │  (×N per step)
  │ ◄── data: {"type":"execution_complete"}  ◄── {summary: {}} │
  │  Stream 2 closes              │                            │
```

---

### How the frontend reads the stream

The frontend uses `fetch()` with the `ReadableStream` API — **not** `EventSource`. This allows passing an `Authorization` header, which `EventSource` does not support.

```javascript
// In frontend/src/api.js — streamChat()
const response = await fetch(`${API_BASE}/stream/chat`, {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,   // EventSource can't send this
    },
    body: JSON.stringify({ message }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = '';

while (true) {
    const { done, value } = await reader.read();   // blocks until data arrives

    if (done) break;   // ← stream ended, HTTP connection closed

    buffer += decoder.decode(value, { stream: true });

    // SSE events are delimited by \n\n
    const parts = buffer.split('\n\n');
    buffer = parts.pop();   // keep incomplete last chunk

    for (const part of parts) {
        const line = part.trim();
        if (line.startsWith('data: ')) {
            const event = JSON.parse(line.slice(6));
            handleEvent(event);   // route by event.type
        }
    }
}
```

**How the stream ends:**

| What happens on the server | What the frontend sees |
|---|---|
| Python `async for chunk in graph.astream(...)` exhausts | FastAPI `StreamingResponse` generator returns |
| FastAPI closes the HTTP response body | `reader.read()` returns `{ done: true, value: undefined }` |
| `while(true)` loop hits `if (done) break` | Frontend cleans up state, re-enables input |

There is **no explicit "end" SSE event** needed — the HTTP connection closing is the signal.

---

### Single stream vs multiple concurrent streams

**Per user, per message = one stream:**

Each `POST /stream/chat` or `GET /sessions/{id}/execute` opens exactly one HTTP connection that streams until complete, then closes. The next user message opens a brand new HTTP connection.

```
Message 1:  POST → [stream opens] ──── [events] ──── [stream closes]
Message 2:                                               POST → [stream opens] ──── [stream closes]
```

**Multiple concurrent users = multiple independent streams:**

Each user's request is handled by a separate asyncio coroutine in FastAPI. There is no shared global stream state — each `agent.astream()` call is independent.

```
User A:  POST /stream/chat ─── [coroutine A] ─── SSE stream A ──► Browser A
User B:  POST /stream/chat ─── [coroutine B] ─── SSE stream B ──► Browser B
User C:  POST /stream/chat ─── [coroutine C] ─── SSE stream C ──► Browser C
         (all three run concurrently in the same FastAPI process via asyncio)
```

**Plan mode — two streams, same session:**

The plan stream (Stream 1) and execute stream (Stream 2) are sequential, not concurrent. Stream 1 closes before the user triggers Stream 2. They share the same `thread_id`/`session_id` but never overlap.

---

## 9. Concurrent Input: What Happens When AI Is Running

### Chat Mode (LangGraph ReAct)

Each chat message starts a **new `agent.astream()` call** on the same `thread_id`. The `MongoDBSaver` uses the checkpoint to load prior messages as context. There is **no distributed locking** — if two requests arrive with the same `thread_id` simultaneously:

- Both will read the same latest checkpoint as their starting state
- Both will write their own new checkpoint when they complete
- The second to finish will overwrite the first's checkpoint (last write wins)

**Practical behaviour:** The frontend disables the input while a response is streaming (`Send` button → `Stop` button), preventing this race in practice. If a user refreshes mid-stream, the next message will work fine — it picks up the last completed checkpoint.

### Plan Mode — Concurrent Sends During Approval Wait

The plan session is paused at an `interrupt()` before the `approval` node. During this time:

- `GET /sessions/{id}/plan` will return the existing plan (no new graph execution)
- `PUT /sessions/{id}/plan` updates plan state via `aupdate_state()` safely
- `POST /sessions/{id}/message` calls `interrupt_and_replan()` which:
  1. Gets current state
  2. Updates goal + resets approval via `aupdate_state(as_node="planner")`
  3. Calls `graph.ainvoke(None, config)` to re-run from planner

### Plan Mode — New Input During Active Execution

When `GET /sessions/{id}/execute` is streaming (graph is running tasks), and the client calls `POST /sessions/{id}/message`:

```python
# interrupt_and_replan() in graph.py:
await graph.aupdate_state(
    config,
    {"goal": new_input, "status": "replanning", "approved": False, "current_step": 0},
    as_node="planner"
)
await graph.ainvoke(None, config)  # Re-runs from planner
```

The state update is written to the checkpoint. The currently running `astream()` task will observe the state change when the next node reads state. **There is no explicit cancellation** of the in-flight execution — currently running tasks (especially parallel `task_executor` nodes) will complete, then the aggregator will read the updated state and route to `summary` if `status != "executing"`.

### Plan Mode — Stop During Execution

`POST /sessions/{id}/stop` calls `stop_execution()`:

```python
await graph.aupdate_state(config, {"status": "stopped"})
```

The `should_continue()` router reads `state.status` after each step and returns `"summary"` if status is `"stopped"`. So execution stops cleanly at the **end of the current step** (not mid-task). In-flight parallel tasks for the current step will still complete.

### Google ADK — Concurrent Input

ADK's `Runner.run_async()` holds conversation state in `InMemorySessionService`. Two simultaneous `run_async()` calls on the same `session_id` will both read and write the same in-memory session object with no locking — this is a concurrency risk not guarded against in the ADK implementation.

---

## 10. LangGraph vs Google ADK Side-by-Side

| Aspect | LangGraph | Google ADK |
|---|---|---|
| **Framework** | `langgraph` + `langchain-*` | `google-adk` |
| **Agent type** | `create_react_agent` (chat) / custom `StateGraph` (plan) | `LlmAgent` + `Runner` |
| **Tool binding** | `MultiServerMCPClient.get_tools()` → LangChain tool objects | `MCPToolset` attached to agent at construction |
| **Tool auth** | JWT injected into HTTP header at client creation time | JWT passed as text in user message (workaround) |
| **Conversation memory** | `MongoDBSaver` checkpointer — survives restart | `InMemorySessionService` — lost on restart |
| **Plan persistence** | Full state in MongoDB checkpoints (automatic) | Metadata only in `agent_sessions` (manual writes) |
| **Parallel execution** | `Send()` fan-out — true parallel graph branches | Sequential step-by-step |
| **Human-in-the-loop** | `interrupt()` / `Command(resume=...)` — built-in | Not built-in (manual workflow control) |
| **Custom state injection** | `graph.aupdate_state(config, patch, as_node=...)` | Direct MongoDB write + mutate session in memory |
| **Streaming** | `graph.astream(stream_mode="updates" or "values")` | `runner.run_async()` is an async generator |
| **Boilerplate** | High for custom graph (nodes, edges, state, reducers) | Low — `LlmAgent` + `Runner` is ~10 lines |
| **Code to delete** | `ai_service.execute_task()` MCP branch (dead code, never reached) | Nothing equivalent |
| **Best for** | Complex multi-step workflows with approval, parallel tasks, retry | Simple chat agents and sequential plans |

---

## Quick Reference: Key API Calls

```python
# --- LangGraph ---

# Read state
state = await graph.aget_state({"configurable": {"thread_id": tid}})
values = state.values                  # Full AgentState dict
next_nodes = list(state.next)          # What runs next
has_interrupt = bool(state.tasks)      # Waiting for resume?

# Write state manually
await graph.aupdate_state(config, patch, as_node="planner")

# Resume from interrupt
from langgraph.types import Command
await graph.ainvoke(Command(resume={"approved": True}), config)

# Stream execution
async for chunk in graph.astream(initial_state, config, stream_mode="updates"):
    for node_name, output in chunk.items():
        ...

# Read chat history from checkpointer
checkpoint = checkpointer.get(config)           # sync, returns dict
messages = checkpoint["channel_values"]["messages"]

# --- Google ADK ---

# Create session
await session_service.create_session(app_name=..., user_id=..., session_id=..., state={...})

# Run agent turn
async for event in runner.run_async(user_id=..., session_id=..., new_message=Content(...)):
    for part in event.content.parts:
        if hasattr(part, "function_call"):  ...  # tool call
        elif hasattr(part, "text"):         ...  # text response

# Read/write ADK session state (in-memory)
session = await session_service.get_session(...)
session.state["my_key"] = "my_value"
```
