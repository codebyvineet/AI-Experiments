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
12. [Sub-Agents and Multi-Agent Patterns](#12-sub-agents-and-multi-agent-patterns)
13. [Session Registry: Framework-Agnostic Session Management](#13-session-registry-framework-agnostic-session-management)
14. [Long-running Task Resilience: SSE Disconnect Behaviour](#14-long-running-task-resilience-sse-disconnect-behaviour)
15. [Implementing Long-running Tools](#15-implementing-long-running-tools)
16. [How MCP Requests Are Authenticated](#16-how-mcp-requests-are-authenticated)
17. [Token Generation from User Identity](#17-token-generation-from-user-identity)

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

ADK now uses `MongodbSessionService` (from the `adk-mongodb-session` package) for **fully persistent** storage — analogous to LangGraph's `MongoDBSaver`. Both conversation history (events) and plan state survive app restarts.

`MongodbSessionService` is configured with **4 collection references** (prefixed by `collection_prefix`, set to `"adk"` in this project), but MongoDB only creates a collection when the first document is written to it:

| Collection | `_id` key | Created in this project? | Purpose |
|---|---|---|---|
| `adk_sessions` | session UUID | **Yes** — on `create_session()` | One document per session — metadata, state, timestamps |
| `adk_events` | event UUID | **Yes** — on every `run_async()` turn | One document per turn event — conversation history, tool calls, results |
| `adk_app_states` | `app_name` | **No** — never written | Shared state for keys prefixed `"app:"` — not used in this project |
| `adk_user_states` | `"{app_name}_{user_id}"` | **No** — never written | Shared state for keys prefixed `"user:"` — not used in this project |

The `adk_app_states` and `adk_user_states` collections only get created if application code sets state keys with the `"app:"` or `"user:"` prefixes (ADK's 3-tier state scoping). This project uses only unscoped keys (`"mode"`, `"plan"`, `"goal"`, etc.), so all state goes into `adk_sessions.state` and those two collections are never written to.

> **Legacy collection: `agent_sessions`** — You may also see an `agent_sessions` collection in MongoDB. This was created by the **pre-`MongodbSessionService` version** of the ADK code (commit `a5e30fb`), which manually called `db.agent_sessions.update_one(...)` in `_load_session_meta()` and `_update_session_meta()`. The current code has no reference to this collection. It is a leftover from older runs and can be safely dropped: `db.agent_sessions.drop()`.

> **What is `app_name`?** It is a namespace string — `"adk_demo"` in this project, set as `ADKAgentManager.APP_NAME`. It scopes all sessions so that multiple applications can share the same MongoDB database without colliding. Every `create_session()`, `get_session()`, and `list_sessions()` call filters by `app_name`.

---

**`adk_sessions` document** (exact fields from source):

```json
{
  "_id": "550e8400-e29b-41d4-a716-446655440000",
  "app_name": "adk_demo",
  "user_id": "user_demo",
  "state": {
    "mode": "plan",
    "is_planning_mode": true,
    "goal": "Create two items and verify",
    "plan": [
      {"step_id": "1", "description": "Create item Alpha", "action": "create_item", "parameters": {"name": "Alpha"}, "group": 1, "status": "completed", "result": {"text": "..."}},
      {"step_id": "2", "description": "Create item Beta",  "action": "create_item", "parameters": {"name": "Beta"},  "group": 1, "status": "completed", "result": {"text": "..."}},
      {"step_id": "3", "description": "List all items to verify", "action": "list_items", "parameters": {}, "group": 2, "status": "pending"}
    ],
    "current_step": 1,
    "is_complete": false,
    "archived": false,
    "last_message": "Create two items and verify"
  },
  "create_time": ISODate("2026-03-03T09:00:00Z"),
  "update_time": ISODate("2026-03-03T09:05:00Z")
}
```

> **State scoping:** The `state` field only contains session-scoped keys. Keys prefixed `"app:"` go to `adk_app_states`; keys prefixed `"user:"` go to `adk_user_states`. Keys prefixed `"temp:"` are never persisted. All three are merged back into `session.state` when reading.

---

**`adk_events` document** (exact fields from source):

```json
{
  "_id": "event-uuid-...",
  "app_name": "adk_demo",
  "user_id": "user_demo",
  "session_id": "550e8400-...",
  "invocation_id": "inv-uuid-...",
  "author": "user",
  "content": {
    "role": "user",
    "parts": [
      {"text": "Create two items called Alpha and Beta"}
    ]
  },
  "actions": "<pickle bytes>",
  "branch": null,
  "timestamp": ISODate("2026-03-03T09:00:01Z"),
  "long_running_tool_ids": [],
  "partial": false,
  "turn_complete": true,
  "error_code": null,
  "error_message": null,
  "interrupted": false,
  "grounding_metadata": null,
  "custom_metadata": null
}
```

> **`author` values**: `"user"` for user messages, `"chat_agent"` / `"planner_agent"` for AI responses (the agent's `name` field).

> **`content.parts` types** — all AI event types appear as different part shapes:
> - Text response: `{"text": "Done! I created Alpha and Beta."}`
> - Tool call: `{"function_call": {"name": "create_item", "args": {"name": "Alpha", "auth_token": "..."}}}`
> - Tool result: `{"function_response": {"name": "create_item", "response": {"output": "..."}}}`

> **`actions` is `pickle` bytes** — stored as binary, not JSON. Contains `EventActions` with `state_delta`, `artifact_delta`, `transfer_to_agent`, etc. Cannot be decoded from raw MongoDB without Python + the ADK library.

> **Partial events are NOT saved** — `append_event()` returns early if `event.partial is True`. Only complete events hit MongoDB.

All conversation events (user messages, AI responses, tool calls, tool results) are written to `adk_events` automatically by `append_event()` on every `run_async()` turn. Plan step updates use `_update_session_state()` which writes `state.{key}` dot-notation patches directly to `adk_sessions`.

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
# Via the ADK manager (API-level access) — persisted to MongoDB
state = await adk_agent.get_session_state(session_id, user_id=user_id)
# Returns: {"session_id", "user_id", "mode", "goal", "plan", "current_step", "is_complete", "event_count", ...}

# Via the framework's session service directly
session = await adk_agent._session_service.get_session(
    app_name="adk_demo",
    user_id=user_id,
    session_id=session_id,
)
# session.state = {"mode": "plan", "plan": [...], "current_step": 1, ...}
# session.events = [Event(...), ...]  ← full conversation history, survives restart

# List all sessions for a user
response = await adk_agent._session_service.list_sessions(app_name="adk_demo", user_id=user_id)
for s in response.sessions:
    print(s.id, s.state)

# Raw MongoDB query on the framework's collection (e.g. for admin listing)
coll = adk_agent._session_service.sessions_collection
for doc in coll.find({"user_id": user_id}).sort("update_time", -1):
    print(doc["_id"], doc["state"])
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
| **Session persistence** | `MongodbSessionService` stores all events (messages, tool calls, results) and state in MongoDB automatically — survives restarts |
| **Event streaming** | `run_async()` is an async generator that yields `Event` objects as the agent acts |
| **Multi-turn memory** | Conversation history persists across turns and restarts via MongoDB event log |
| **Session listing** | `session_service.list_sessions(app_name, user_id)` returns all sessions for a user |

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

### Google ADK — Minimal Agent (with MongoDB persistence)

```python
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.tools.mcp_tool import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.genai.types import Content, Part
from adk_mongodb_session.mongodb.sessions.mongodb_session_service import MongodbSessionService

# 1. Tools
toolset = MCPToolset(connection_params=StreamableHTTPConnectionParams(url="http://mcp-server:8001/mcp"))

# 2. Agent
agent = LlmAgent(
    model="gemini-2.5-pro",
    name="my_agent",
    instruction="You are a helpful assistant. Use tools when needed.",
    tools=[toolset],
)

# 3. MongoDB-backed session service (persists conversation history across restarts)
session_service = MongodbSessionService(
    db_url="mongodb://localhost:27017",
    database="mcp_demo",
    collection_prefix="adk",   # creates adk_sessions, adk_events, etc.
)

# 4. Runner
runner = Runner(agent=agent, app_name="my_app", session_service=session_service)

# 5. Create session (done once — session persists in MongoDB)
await session_service.create_session(
    app_name="my_app", user_id="user1", session_id="s1",
    state={"mode": "chat", "is_complete": False}
)

# 6. Run — subsequent turns on the same session_id continue the conversation
async for event in runner.run_async(
    user_id="user1",
    session_id="s1",
    new_message=Content(role="user", parts=[Part.from_text("how many items?")])
):
    if not event.content or not event.content.parts:
        continue
    for part in event.content.parts:
        if hasattr(part, "text") and part.text:
            print("TEXT:", part.text)
        elif hasattr(part, "function_call") and part.function_call:
            print("TOOL CALL:", part.function_call.name)
        elif hasattr(part, "function_response") and part.function_response:
            print("TOOL RESULT:", part.function_response.name)
```

This project uses **two runners** — one for chat, one for the planner — both sharing the same `MongodbSessionService`:

```python
# In ADKAgentManager.initialize():
self._chat_runner = Runner(agent=_build_chat_agent(),    app_name=APP_NAME, session_service=self._session_service)
self._plan_runner = Runner(agent=_build_planner_agent(), app_name=APP_NAME, session_service=self._session_service)
```

> **`app_name` explained:** `APP_NAME = "adk_demo"` is a namespace string that scopes all sessions. It is required by every `Runner`, `create_session()`, `get_session()`, and `list_sessions()` call. It becomes the `_id` in `adk_app_states` and the first part of the `_id` in `adk_user_states` (`"adk_demo_user_demo"`). If you renamed this app or ran a second app against the same MongoDB, you would use a different `app_name` — sessions from one app are never visible to another. In this project it is hardcoded as the class constant `ADKAgentManager.APP_NAME`.

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

ADK wires tools by attaching `MCPToolset` to the `LlmAgent` at construction time:

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

ADK uses two separate agents and two separate runners:

| Agent | Runner | Role | Tools |
|---|---|---|---|
| `planner_agent` | `_plan_runner` | Generates JSON plan — instructed NOT to call tools | MCPToolset (for schema awareness only) |
| `chat_agent` | `_chat_runner` | Executes each step using MCP tools | MCPToolset (actively calls tools) |

The planner is given `MCPToolset` so it can see the real tool names and parameter schemas. Its system instruction explicitly forbids it from making tool calls — it must output a raw JSON array only.

`execute_step()` handles one step at a time (for step-by-step UI control). `execute_all_steps()` handles the full plan using ADK's native `SequentialAgent` + `ParallelAgent` hierarchy built dynamically at runtime from the `group` field.

**ADK plan flow:**
```
POST /agent/sessions/{id}/plan  →  _plan_runner.run_async("Generate a plan for: {goal}")
                                    → planner outputs raw JSON array
                                       each step has: {step_id, description, action, parameters,
                                                        group (int), status: "pending"}
                                    → _update_session_state({plan, goal, current_step: 0})
                                    → returns {plan, total_steps}

POST /agent/sessions/{id}/execute-step  →  execute_step()
                                            → dynamically creates LlmAgent for the single step
                                            → new Runner.run_async() — result stored via output_key
                                            → _update_session_state({plan, current_step: N+1})
                                            → returns {step, is_complete}

POST /agent/sessions/{id}/execute-all   →  execute_all_steps()
                                            → _build_execution_pipeline(remaining_steps, auth_token)
                                            → single runner.run_async("Proceed.") triggers full pipeline
                                            → results stored in session.state via output_key per step
                                            → returns {execution_results, status: "completed"}
```

**Parallel execution via ADK native `SequentialAgent` + `ParallelAgent`:**

`_build_execution_pipeline()` reads the `group` field from each plan step and dynamically constructs an agent hierarchy at runtime — no hardcoded structure:

```
Plan: [
  {step_id: "1", group: 1, action: "create_item", ...},
  {step_id: "2", group: 1, action: "create_item", ...},
  {step_id: "3", group: 2, action: "list_items",  ...},
]

Pipeline built at runtime:
  SequentialAgent("execution_pipeline")
  ├── ParallelAgent("parallel_group_1")        ← group 1 (two steps → ParallelAgent)
  │     ├── LlmAgent("step_1_executor")  output_key="step_1_result"
  │     └── LlmAgent("step_2_executor")  output_key="step_2_result"
  ├── LlmAgent("step_3_executor")              ← group 2 (single step → bare LlmAgent)
  │     output_key="step_3_result"
  └── LlmAgent("execution_summary")            ← always appended; reads all step results
        output_key="execution_summary"
```

Each step executor is an `LlmAgent` with `output_key=f"step_{step_id}_result"` — ADK automatically writes the agent's final text output to `session.state[output_key]` after the turn. The summary agent's instruction references all `{step_N_result}` template vars, which ADK resolves from session state before the agent runs.

A single `runner.run_async("Proceed.")` drives the entire pipeline. ADK handles all scheduling — `ParallelAgent` fans out concurrently, `SequentialAgent` enforces group ordering. This is equivalent to LangGraph's `Send()` fan-out but using ADK's native orchestration primitives instead of manual `asyncio.gather`.

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

### Google ADK — Automatic via MongodbSessionService

`MongodbSessionService` handles persistence automatically on the same model as LangGraph's `MongoDBSaver`:

| What | Where | Who writes it |
|---|---|---|
| Conversation events (messages, tool calls, tool results) | `adk_sessions` event log | Framework — on every `run_async()` turn |
| Session state (plan, step, mode, goal) | `adk_sessions` state field | App code — via `_update_session_state()` |

**Automatic (zero app code):** Every `runner.run_async()` call appends all events (user message, AI response, tool calls, tool results) to the session's event log in MongoDB. No checkpoint config needed — it's built into `MongodbSessionService`.

**Manual state updates** are only needed for plan metadata that changes outside of a `run_async()` turn:

```python
def _update_session_state(self, session_id: str, updates: dict) -> None:
    """Update specific state keys directly in the framework's MongoDB collection."""
    set_fields = {f"state.{k}": v for k, v in updates.items()}
    self._session_service.sessions_collection.update_one(
        {"_id": session_id},
        {"$set": set_fields},
    )

# Called when plan is generated, step completes, or session is archived:
self._update_session_state(session_id, {"plan": plan, "current_step": 0, "is_complete": False})
self._update_session_state(session_id, {"current_step": next_step, "is_complete": is_complete})
```

If the process restarts, **both conversation history and plan state survive** — unlike the previous `InMemorySessionService` implementation where conversation history was lost.

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

### Google ADK — `_update_session_state()` helper

There is no equivalent to `aupdate_state` in ADK. `MongodbSessionService` has no patch API. Instead, `adk_agent.py` uses a thin helper that writes directly to `adk_sessions`:

```python
async def _update_session_state(self, session_id: str, updates: dict):
    """Direct $set patch on adk_sessions.state — used for out-of-band state changes."""
    update_ops = {f"state.{k}": v for k, v in updates.items()}
    await db.adk_sessions.update_one(
        {"_id": session_id},
        {"$set": update_ops}
    )

# Examples:
await self._update_session_state(session_id, {"plan": updated_plan, "current_step": 2})
await self._update_session_state(session_id, {"is_complete": True})
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

ADK's `Runner.run_async()` reads and writes session state via `MongodbSessionService`. Two simultaneous `run_async()` calls on the same `session_id` will both read the same session snapshot from MongoDB at call time, then each write their own event updates back — there is no distributed locking. Last write wins for the session state document. This is a concurrency risk not guarded against in the ADK implementation, but in practice the frontend ensures at most one active `run_async()` per session at a time.

---

## 10. LangGraph vs Google ADK Side-by-Side

| Aspect | LangGraph | Google ADK |
|---|---|---|
| **Framework** | `langgraph` + `langchain-*` | `google-adk` |
| **Agent type** | `create_react_agent` (chat) / custom `StateGraph` (plan) | `LlmAgent` + `Runner` |
| **Tool binding** | `MultiServerMCPClient.get_tools()` → LangChain tool objects | `MCPToolset` attached to agent at construction |
| **Tool auth** | JWT injected into HTTP header at client creation time | JWT passed as text in user message (workaround) |
| **Conversation memory** | `MongoDBSaver` checkpointer — survives restart | `MongodbSessionService` — survives restart |
| **Plan persistence** | Full state in MongoDB checkpoints (automatic) | State in framework's `adk_sessions` (mixed: events auto, plan state via manual `_update_session_state()`) |
| **Parallel execution** | `Send()` fan-out — true parallel graph branches | `SequentialAgent` + `ParallelAgent` hierarchy built dynamically from `group` field in `_build_execution_pipeline()` |
| **Human-in-the-loop** | `interrupt()` / `Command(resume=...)` — built-in | Not built-in (manual workflow control) |
| **Custom state injection** | `graph.aupdate_state(config, patch, as_node=...)` | Direct MongoDB write via `_update_session_state()` helper |
| **Streaming** | `graph.astream(stream_mode="updates" or "values")` | `runner.run_async()` is an async generator |
| **Runners** | Single compiled graph | Two separate `Runner` instances (chat + planner), shared session service |
| **Boilerplate** | High for custom graph (nodes, edges, state, reducers) | Low — `LlmAgent` + `Runner` is ~10 lines |
| **Code to delete** | `ai_service.execute_task()` MCP branch (dead code, never reached) | Nothing equivalent |
| **Best for** | Complex multi-step workflows with approval, parallel tasks, retry | Simple chat agents and sequential plans |

---

## 12. Sub-Agents and Multi-Agent Patterns

Sub-agents allow one agent to delegate work to another specialised agent. Both frameworks support this, but with very different mechanics. This section covers all available patterns and step-by-step recipes for chat mode and plan mode in each framework.

---

### What "sub-agent" means in each framework

| Concept | Google ADK | LangGraph |
|---|---|---|
| A coordinator that calls sub-agents | `SequentialAgent` / `ParallelAgent` as the root | `create_supervisor()` from `langgraph-supervisor` package, or manual supervisor node |
| A specialised worker agent | `LlmAgent` listed in `sub_agents=[...]` | `create_react_agent()` passed to `create_supervisor(agents=[...])`, or a compiled subgraph node |
| One agent calling another on demand | `AgentTool` wraps an agent as a callable tool | Tool-wrapped subgraph (`@tool`), or `create_handoff_tool(agent_name=...)` from `langgraph-supervisor` |
| Agents run one after another | `SequentialAgent` | Edges between nodes, or `Command(goto=...)` chain |
| Agents run in parallel | `ParallelAgent` | `Send()` fan-out from a conditional edge |
| Agent loops until done | `LoopAgent` | Cycle in the graph (`should_continue` edge loops back) |

> **Current state in this project:**
> - **ADK**: `SequentialAgent` and `ParallelAgent` are **already in production use**. `execute_all_steps()` calls `_build_execution_pipeline()` which dynamically constructs a `SequentialAgent` → `ParallelAgent` hierarchy at runtime from the plan's `group` field. Each step executor is an `LlmAgent` with `output_key` — results flow through session state automatically. A summary `LlmAgent` is always appended at the end. `AgentTool` is not yet used.
> - **LangGraph**: `Send()` fan-out is already used for parallel task execution in plan mode. Subgraphs, supervisor patterns, and `Command(goto=...)` handoffs are not yet used.
>
> The patterns below are step-by-step guides for adding formal sub-agent support to either framework.

---

### Google ADK — Sub-Agent Types

ADK provides four built-in orchestration agents. All live under `google.adk.agents`:

| Class | Import | What it does |
|---|---|---|
| `SequentialAgent` | `from google.adk.agents import SequentialAgent` | Runs `sub_agents` one after another; each gets the full session history |
| `ParallelAgent` | `from google.adk.agents import ParallelAgent` | Runs all `sub_agents` concurrently; results merged back into session |
| `LoopAgent` | `from google.adk.agents import LoopAgent` | Runs a single sub-agent repeatedly until it outputs a special stop signal or `max_iterations` is hit |
| `AgentTool` | `from google.adk.tools import agent_tool` | Wraps any `LlmAgent` as a callable tool — so an orchestrator can invoke it like a function call |

---

### ADK — Sub-Agents in Chat Mode

**Pattern: `AgentTool` — orchestrator delegates to a specialist on demand**

Use this when a general chat agent needs to hand off specific queries to a specialist (e.g., a "data analyst" agent, a "summariser" agent).

**Step 1 — Define the specialist agent:**

```python
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

specialist = LlmAgent(
    model="gemini-2.5-pro",
    name="data_analyst",
    instruction="""You are a data analyst. Given raw tool results, produce
    a clear, concise summary with counts, highlights, and recommendations.
    Do not call any tools yourself — analyse the data given to you.""",
    # No tools — pure reasoning agent
)
```

**Step 2 — Wrap the specialist as an `AgentTool`:**

```python
from google.adk.tools import agent_tool

analyst_tool = agent_tool.AgentTool(agent=specialist)
# This creates a tool named "data_analyst" that the orchestrator can call like any MCP tool
```

**Step 3 — Add the tool to the orchestrator agent:**

```python
orchestrator = LlmAgent(
    model="gemini-2.5-pro",
    name="chat_agent",
    instruction="""You are a helpful assistant. You have access to MCP tools for
    item management AND a data_analyst sub-agent tool.

    When the user asks you to analyse, summarise, or draw conclusions from data,
    first call the relevant MCP tools to fetch the data, then call data_analyst
    to interpret it. Always pass auth_token to MCP tools.""",
    tools=[
        _make_mcp_toolset(),   # MCP tools for CRUD
        analyst_tool,          # Sub-agent as a tool
    ],
)
```

**Step 4 — Run exactly as before — no changes to the Runner:**

```python
runner = Runner(agent=orchestrator, app_name=APP_NAME, session_service=session_service)

async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=...):
    # Framework handles the orchestrator → AgentTool → specialist → orchestrator loop
    for part in event.content.parts:
        if hasattr(part, "text"):            print("TEXT:", part.text)
        elif hasattr(part, "function_call"): print("TOOL CALL:", part.function_call.name)
```

**What happens at runtime:**

```
User: "fetch all items and tell me what's interesting"
     │
     ▼
orchestrator LlmAgent
     ├── Calls list_items (MCP tool) → gets raw data
     └── Calls data_analyst (AgentTool) with raw data as argument
              │
              ▼
         specialist LlmAgent runs separately
              └── Returns summary text
     │
     ▼
orchestrator uses summary to form final reply
```

> **Session note:** `AgentTool` creates a **nested runner** with its own ephemeral session inside the parent runner's turn. The specialist's events appear as `function_call` / `function_response` parts in the orchestrator's event stream — they are logged to the same MongoDB session automatically.

---

### ADK — Sub-Agents in Plan Mode

**Pattern: `SequentialAgent` — planner → executor pipeline as a single agent graph**

Instead of manually calling `_plan_runner` then `_chat_runner`, you can declare the pipeline as a `SequentialAgent` and let the framework handle the handoff.

**Step 1 — Define planner and executor agents:**

```python
from google.adk.agents import LlmAgent, SequentialAgent

planner = LlmAgent(
    model="gemini-2.5-pro",
    name="planner_agent",
    instruction="""You are a planning agent. Given a user goal, output a raw JSON
    array of steps. Each step: {step_id, description, action, parameters, status: "pending"}.
    Return ONLY the JSON array — no prose, no markdown fences.
    You can see tool schemas but must NOT call any tools.""",
    tools=[_make_mcp_toolset()],   # schema visibility only
    output_key="plan_json",        # stores output in session.state["plan_json"]
)

executor = LlmAgent(
    model="gemini-2.5-pro",
    name="executor_agent",
    instruction="""You are an execution agent. Read session.state["plan_json"] to find
    the plan. Execute each step in order using the MCP tools. After each step, update
    your progress. Always pass auth_token to tools.""",
    tools=[_make_mcp_toolset()],
)
```

**Step 2 — Compose into a `SequentialAgent`:**

```python
plan_and_execute = SequentialAgent(
    name="plan_and_execute_pipeline",
    sub_agents=[planner, executor],
    # planner runs first, its output is in session state, then executor runs
)
```

**Step 3 — Single runner, single `run_async` call:**

```python
runner = Runner(
    agent=plan_and_execute,
    app_name=APP_NAME,
    session_service=session_service,
)

# Single call executes the full pipeline: plan → execute
async for event in runner.run_async(user_id=..., session_id=..., new_message=Content(...)):
    ...
```

**What happens at runtime:**

```
run_async("List all items and create a summary doc")
     │
     ├── planner_agent runs
     │     └── outputs JSON plan → stored in session.state["plan_json"]
     │
     └── executor_agent runs (with plan visible in session state)
           ├── Reads session.state["plan_json"]
           ├── Calls list_items MCP tool (step 1)
           └── Calls create_item MCP tool (step 2)
```

**Adding parallel execution with `ParallelAgent`:**

For steps that can run concurrently, wrap them in a `ParallelAgent` inside the sequence:

```python
from google.adk.agents import ParallelAgent

# Two independent research agents running at the same time
fetch_items = LlmAgent(name="fetch_items", tools=[_make_mcp_toolset()],
    instruction="Call list_items and store results. Always pass auth_token.")
fetch_meta = LlmAgent(name="fetch_meta", tools=[_make_mcp_toolset()],
    instruction="Call get_item_metadata and store results. Always pass auth_token.")

parallel_fetchers = ParallelAgent(
    name="parallel_fetch",
    sub_agents=[fetch_items, fetch_meta],
)

summariser = LlmAgent(name="summariser",
    instruction="Read both fetch results from session state and produce a summary.")

pipeline = SequentialAgent(
    name="pipeline",
    sub_agents=[parallel_fetchers, summariser],  # parallel fetch, then sequential summary
)
```

**`LoopAgent` — retry until success:**

```python
from google.adk.agents import LoopAgent

validator = LlmAgent(
    name="step_executor",
    instruction="""Execute the current pending step from session.state["plan"].
    If the step succeeds, output: {"status": "done"}.
    If it fails due to a transient error, output: {"status": "retry"}.
    The loop stops when you output {"status": "done"}.""",
    tools=[_make_mcp_toolset()],
)

retry_executor = LoopAgent(
    name="retry_executor",
    sub_agents=[validator],
    max_iterations=3,   # stop after 3 attempts even if not "done"
)
```

---

### Google ADK — Key Principles for Sub-Agents

1. **State passing between sequential agents:** Use `output_key="my_key"` on a sub-agent — its text output is automatically stored in `session.state["my_key"]`. The next agent reads it via its instruction.
2. **Parallel agents share the same session:** All parallel sub-agents read from and write to the same session state. Use distinct `output_key` values to avoid collisions.
3. **`AgentTool` creates an ephemeral sub-session:** The specialist runs in a throwaway session scoped to the parent's current turn. Its tool calls appear in the parent's event stream.
4. **All events persist:** The `MongodbSessionService` logs every event from every sub-agent to MongoDB automatically — the full trace is available after the run.

---

### LangGraph — Sub-Agent Types

LangGraph core doesn't have dedicated sub-agent classes like ADK's `SequentialAgent` / `ParallelAgent`. Instead it uses **graph composition** patterns. For the supervisor pattern specifically, a first-party package `langgraph-supervisor` provides higher-level prebuilts:

```bash
pip install langgraph-supervisor   # separate package, maintained by LangChain team
```

```python
from langgraph_supervisor import create_supervisor, create_handoff_tool
from langgraph.prebuilt import create_react_agent
```

> **Recommendation from LangChain docs (2025):** For most supervisor use-cases, implementing the pattern directly via tools (`create_react_agent` + `create_handoff_tool`) is preferred over the `create_supervisor()` wrapper — it gives more control with less abstraction overhead.

| Pattern | Mechanism | Package | When to use |
|---|---|---|---|
| **Subgraph as node** | Compile a child `StateGraph`, call it as a node in the parent | `langgraph` core | Encapsulate a reusable multi-step workflow |
| **`Send()` fan-out** | Conditional edge returns `List[Send]` to spawn N parallel node instances | `langgraph` core | Already used in this project for parallel tasks |
| **`Command(goto=...)` handoff** | A node returns `Command(goto="other_node", update={...})` | `langgraph` core | One agent explicitly passes control to another |
| **Tool-wrapped subgraph** | Compile a subgraph, wrap it as a `@tool`, give it to a `create_react_agent` | `langgraph` core | ReAct agent that delegates to a full subgraph |
| **Supervisor (prebuilt)** | `create_supervisor(agents=[...], model=..., prompt=...)` — central LLM routes to sub-agents via `create_handoff_tool` | `langgraph-supervisor` | Hierarchical teams; one supervisor coordinates N specialists |

---

### LangGraph — Sub-Agents in Chat Mode

**Pattern A: Tool-wrapped sub-agent — orchestrator delegates via tool call**

This is the LangGraph equivalent of ADK's `AgentTool`. The specialist is a compiled graph exposed as a LangChain `@tool`.

**Step 1 — Define and compile the specialist subgraph:**

```python
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import create_react_agent
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

# Specialist: a standalone ReAct agent with only analysis tools
analyst_agent = create_react_agent(
    model=ChatVertexAI(model_name="gemini-2.5-pro", ...),
    tools=[],   # no tools — pure reasoning
    prompt="You are a data analyst. Analyse the data passed to you and return a concise summary."
)
```

**Step 2 — Wrap the specialist as a LangChain tool:**

```python
from langchain_core.tools import tool

@tool
def call_data_analyst(data: str) -> str:
    """Analyse raw data and return a concise summary.

    Args:
        data: Raw JSON or text data to analyse.

    Returns:
        A human-readable analysis and summary.
    """
    result = analyst_agent.invoke(
        {"messages": [("user", f"Analyse this data:\n\n{data}")]},
        config={"recursion_limit": 10},
    )
    # Extract the last assistant message
    for msg in reversed(result["messages"]):
        if hasattr(msg, "content") and msg.type == "ai":
            return msg.content if isinstance(msg.content, str) else msg.content[0]["text"]
    return "No analysis produced"
```

**Step 3 — Add the tool to the main chat agent:**

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.mongodb import MongoDBSaver

mcp = MultiServerMCPClient({"main": {"transport": "streamable_http", "url": "...", "headers": {...}}})
mcp_tools = await mcp.get_tools()

# Main agent gets both MCP tools AND the analyst sub-agent tool
chat_agent = create_react_agent(
    model=model,
    tools=mcp_tools + [call_data_analyst],   # <-- sub-agent as a tool
    prompt="You have access to item management tools and a data_analyst sub-agent tool. "
           "Use data_analyst when the user asks for analysis or summaries.",
    checkpointer=MongoDBSaver(...),
)
```

**Step 4 — Stream as normal — no change to the caller:**

```python
async for chunk in chat_agent.astream(
    {"messages": [("user", "fetch all items and analyse them")]},
    stream_mode="updates",
    config={"configurable": {"thread_id": f"chat-{user_id}"}},
):
    for node_name, output in chunk.items():
        for msg in output.get("messages", []):
            print(node_name, msg.type, msg.content)
```

**What happens at runtime:**

```
User: "fetch all items and analyse them"
     │
     ▼
agent node (main LLM)
     ├── tool_call: list_items → MCP server
     │        ← ToolMessage with raw item data
     ├── tool_call: call_data_analyst(data="[{...items...}]")
     │        ← calls analyst_agent.invoke() synchronously
     │        ← ToolMessage with analyst's summary text
     └── final AIMessage: "Here are the items. Analysis: ..."
```

---

**Pattern B: `Command`-based handoff — agent routes to a different agent node**

Use when the routing decision is dynamic and you want a different node (not a tool call) to take over completely.

**Step 1 — Define two specialist agent nodes:**

```python
from langgraph.types import Command

async def chat_agent_node(state):
    """General chat agent — routes to analyst if query needs deep analysis."""
    # Simplified: check if the query needs analysis
    last_msg = state["messages"][-1].content
    if "analyse" in last_msg.lower() or "summary" in last_msg.lower():
        return Command(
            goto="analyst_node",          # hand off to analyst
            update={"messages": state["messages"]}  # pass current history
        )
    # Otherwise handle normally
    result = await chat_llm.ainvoke(state["messages"])
    return {"messages": [result]}

async def analyst_node(state):
    """Specialist analyst agent — returns result and hands back to chat agent."""
    result = await analyst_llm.ainvoke(state["messages"])
    return Command(
        goto="chat_agent",              # return control to main agent
        update={"messages": [result]}
    )
```

**Step 2 — Wire into a graph with both nodes:**

```python
builder = StateGraph(ChatState)
builder.add_node("chat_agent", chat_agent_node)
builder.add_node("analyst_node", analyst_node)
builder.add_edge(START, "chat_agent")
# No static edges needed for Command-based handoffs — routing is in the node return value

graph = builder.compile(checkpointer=MongoDBSaver(...))
```

---

### LangGraph — Sub-Agents in Plan Mode

The existing codebase already uses `Send()` for parallel task execution. Here are the two patterns for extending this with full subgraph-based sub-agents.

**Pattern A: `Send()` fan-out — already in this project (parallel tasks)**

This is the simplest form of "parallel sub-agents" in LangGraph — each `Send()` spawns an independent node execution with its own input state:

```python
# nodes.py — already implemented
def create_task_sends(state: AgentState) -> List[Send]:
    """Dispatch each sub-task as a parallel Send() to task_executor."""
    step = plan[current_step]
    return [
        Send("task_executor", {
            "session_id": state["session_id"],
            "task": task,
            "previous_results": [...],
        })
        for i, task in enumerate(step["sub_tasks"])
    ]

# The graph wires this as a conditional edge:
builder.add_conditional_edges("executor_dispatch", create_task_sends)
```

Results are merged via the `Annotated[List[TaskResult], add]` reducer — parallel `task_executor` nodes each append to the same `results` list.

---

**Pattern B: Subgraph as a node — encapsulated specialist pipeline**

Use this when a plan step needs its own multi-step internal logic (e.g., a "research" step that itself involves planning → fetching → synthesising).

**Step 1 — Define the sub-workflow as its own `StateGraph`:**

```python
from langgraph.graph import StateGraph, START, END
from typing import TypedDict

class ResearchState(TypedDict):
    query: str
    raw_data: str
    summary: str
    token: str

async def fetch_node(state: ResearchState):
    """Fetch data via MCP tools."""
    from app.mcp.client import call_mcp_tool
    data = await call_mcp_tool("list_items", {}, state["token"])
    return {"raw_data": str(data)}

async def synthesise_node(state: ResearchState):
    """Use LLM to synthesise the fetched data."""
    result = await llm.ainvoke([("user", f"Summarise: {state['raw_data']}")])
    return {"summary": result.content}

# Compile the sub-workflow
research_builder = StateGraph(ResearchState)
research_builder.add_node("fetch", fetch_node)
research_builder.add_node("synthesise", synthesise_node)
research_builder.add_edge(START, "fetch")
research_builder.add_edge("fetch", "synthesise")
research_builder.add_edge("synthesise", END)

research_subgraph = research_builder.compile()   # no checkpointer — parent handles it
```

**Step 2 — Call the subgraph from a task executor node:**

```python
async def task_executor_node(task_state: dict):
    """Execute a task — delegates to subgraph for complex tasks."""
    task = task_state["task"]

    if task.get("use_subgraph") == "research":
        # Run the research subgraph
        result = await research_subgraph.ainvoke({
            "query": task.get("description", ""),
            "token": task_state["token"],
            "raw_data": "",
            "summary": "",
        })
        return {"results": [TaskResult(
            task_name=task["name"],
            status="success",
            result=result["summary"],
        )]}
    else:
        # Normal MCP tool call path (existing code)
        ...
```

**Step 3 — Or add the subgraph directly as a named node in the parent graph:**

```python
# In graph.py — add the subgraph as a named node
builder.add_node("research_agent", research_subgraph)

# Route certain steps to it via Send()
def create_task_sends(state: AgentState) -> List[Send]:
    step = plan[current_step]
    sends = []
    for i, task in enumerate(step["sub_tasks"]):
        node = "research_agent" if task.get("type") == "research" else "task_executor"
        sends.append(Send(node, {
            "session_id": state["session_id"],
            "token": state["token"],
            "task": task,
            ...
        }))
    return sends
```

---

**Pattern C: Supervisor node — LLM routes to specialist agents dynamically**

The supervisor pattern adds a routing LLM that inspects the current goal and decides which specialist runs next.

```python
from langgraph.types import Command

# Specialist agent nodes
async def crud_agent_node(state: AgentState):
    """Handles item CRUD operations."""
    result = await crud_llm_with_tools.ainvoke(state["messages"])
    return Command(goto="supervisor", update={"messages": [result]})

async def analyst_agent_node(state: AgentState):
    """Handles data analysis and reporting."""
    result = await analyst_llm.ainvoke(state["messages"])
    return Command(goto="supervisor", update={"messages": [result]})

async def supervisor_node(state: AgentState):
    """Routes to the right specialist based on the current task."""
    routing_result = await routing_llm.ainvoke([
        ("system", "You are a router. Output only 'crud_agent' or 'analyst_agent' or 'FINISH'."),
        *state["messages"],
    ])
    choice = routing_result.content.strip()

    if choice == "FINISH":
        return Command(goto=END)
    return Command(goto=choice)

# Graph wiring
builder = StateGraph(AgentState)
builder.add_node("supervisor", supervisor_node)
builder.add_node("crud_agent", crud_agent_node)
builder.add_node("analyst_agent", analyst_agent_node)
builder.add_edge(START, "supervisor")
# No static edges to specialists — Command(goto=...) handles routing at runtime

graph = builder.compile(checkpointer=MongoDBSaver(...))
```

**What the supervisor graph looks like:**

```
START → supervisor
            ├── "crud_agent"   → crud_agent_node → Command(goto="supervisor")
            ├── "analyst_agent"→ analyst_agent_node → Command(goto="supervisor")
            └── "FINISH"       → END
```

The supervisor loop continues until the routing LLM decides the goal is complete.

---

### LangGraph — Key Principles for Sub-Agents

1. **Subgraph checkpointing**: The child `StateGraph` should be compiled **without** a checkpointer — only the parent graph's checkpointer writes to MongoDB. The child's state is ephemeral within the parent's turn.

2. **State type compatibility**: The parent and child graph state types don't need to match. LangGraph uses input/output transformers. If using `Send()`, the sent dict is the child's full input state.

3. **`Send()` results merge via reducers**: Every parallel `task_executor` invocation appends to `AgentState.results` via `Annotated[List[TaskResult], add]`. No explicit join step needed.

4. **`Command(goto=...)` vs edges**: Static edges (`add_edge`) are defined at compile time. `Command(goto=...)` routes dynamically at runtime — use it when the next node depends on what happened in the current node.

5. **Tool-wrapped subgraphs block the event loop**: `call_data_analyst` in Pattern A uses `.invoke()` (synchronous from the tool's perspective). For long-running sub-agents, wrap with `asyncio.get_event_loop().run_in_executor()` or use `ainvoke()`.

---

### Choosing the Right Pattern

| Scenario | ADK | LangGraph |
|---|---|---|
| Chat agent needs a specialist for one type of query | `AgentTool` wrapping an `LlmAgent` | `@tool` wrapping a compiled subgraph, or `create_handoff_tool` |
| Sequential pipeline (plan → execute) | `SequentialAgent([planner, executor])` | Chain of nodes with edges, or `Command(goto=...)` |
| Parallel tasks within a plan step | `ParallelAgent([task_a, task_b])` — **already implemented** | `Send()` fan-out — **already implemented** |
| Hierarchical team (supervisor + N specialists) | `SequentialAgent` / `ParallelAgent` with multiple `LlmAgent` sub-agents | `create_supervisor(agents=[agent_a, agent_b], model=..., prompt=...)` from `langgraph-supervisor` |
| Dynamic routing based on query type | `AgentTool` + routing instruction in orchestrator | `create_supervisor()` with `create_handoff_tool(agent_name=...)` per specialist |
| Retry failed steps | `LoopAgent(max_iterations=3)` | Conditional edge looping back to executor node |
| Encapsulate a reusable multi-step workflow | `SequentialAgent` with named `sub_agents` | Compile subgraph, add as named node |

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

# Create session (persisted to MongoDB via MongodbSessionService)
await session_service.create_session(app_name=..., user_id=..., session_id=..., state={...})

# Run agent turn (events auto-saved to MongoDB)
async for event in runner.run_async(user_id=..., session_id=..., new_message=Content(...)):
    if not event.content or not event.content.parts:
        continue
    for part in event.content.parts:
        if hasattr(part, "function_call"):      ...  # tool call
        elif hasattr(part, "function_response"): ...  # tool result
        elif hasattr(part, "text"):              ...  # text response

# Read session state (from MongoDB)
session = await session_service.get_session(app_name=..., user_id=..., session_id=...)
plan    = session.state["plan"]
events  = session.events   # full conversation history

# List sessions for a user
response = await session_service.list_sessions(app_name=..., user_id=...)

# Write plan metadata outside of run_async (direct MongoDB update)
adk_agent._update_session_state(session_id, {"plan": plan, "current_step": 2})
```

---

## 13. Session Registry: Framework-Agnostic Session Management

### The Problem with the Current Approach

Both frameworks manage their own session storage independently:

| | LangGraph | ADK |
|---|---|---|
| Session ID source | `str(uuid.uuid4())` in `graph.py` | `str(uuid.uuid4())` in `adk_agent.py` |
| Where stored | `checkpoints` collection (binary msgpack) | `adk_sessions` collection (JSON) |
| List sessions via | `db.checkpoints.distinct("thread_id")` + deserialize each | `session_service.list_sessions()` |
| Mode stored? | No — not in checkpoint | Yes — in `adk_sessions.state` |
| Mode restored on refresh? | No — frontend defaults | Stored but frontend never reads it back |
| Created-at timestamp? | Internal checkpoint ts (buried in binary) | `create_time` field in `adk_sessions` |
| Cross-framework query? | Not possible — separate DBs | Not possible |

To list all sessions you must query two different collections in two different databases, deserialise binary blobs for LangGraph, and join on `user_id` manually. There is no single source of truth.

---

### The Session Registry Pattern

The standard production approach is: **your application owns the session lifecycle; the framework is just the execution engine.**

You generate the session ID, write it to your own registry collection *before* handing it to the framework, and the framework stores its checkpoint/event data keyed to that same ID. The registry is always queryable — it never requires deserialising binary blobs.

```
┌──────────┐   POST /sessions    ┌──────────────────┐
│ Frontend │ ─────────────────►  │  Your API        │
└──────────┘                     │  1. gen UUID     │
                                 │  2. write to     │
                                 │     session_     │
                                 │     registry     │
                                 │  3. pass ID to   │
                                 │     framework    │
                                 └────────┬─────────┘
                                          │
                     ┌────────────────────┼──────────────────────┐
                     ▼                    ▼                       ▼
             session_registry        checkpoints           adk_sessions
             (your collection)    (LangGraph internal)  (ADK internal)
             ─────────────────    ────────────────────  ─────────────
             _id: uuid            thread_id: uuid       _id: uuid
             framework: "lg"      checkpoint: <bin>     state: {...}
             mode: "plan"         metadata: <bin>       plan: [...]
             user_id: "..."
             status: "active"
             created_at: ...
             updated_at: ...
```

Both framework collections are keyed to the **same UUID** — `thread_id` in LangGraph and `_id` in ADK sessions. So `session_registry._id` == `checkpoints.thread_id` == `adk_sessions._id`. No join needed — it is the same value.

---

### `session_registry` Collection Schema

```json
{
  "_id": "a3f2b1c4-9e7d-4c2e-b1f3-8d7e6a5b4c3d",
  "user_id": "user_demo",
  "framework": "langgraph",
  "mode": "plan",
  "status": "awaiting_approval",
  "goal": "Create two items and verify they exist",
  "created_at": "2026-03-03T09:00:00Z",
  "updated_at": "2026-03-03T09:05:00Z"
}
```

| Field | Type | Description |
|---|---|---|
| `_id` | UUID string | The session ID — **same value used as LangGraph `thread_id` or ADK session `_id`** |
| `user_id` | string | Owner |
| `framework` | `"langgraph"` \| `"adk"` | Which engine owns the execution state |
| `mode` | `"chat"` \| `"plan"` | UI mode — the single source of truth for the frontend |
| `status` | `"active"` \| `"awaiting_approval"` \| `"executing"` \| `"completed"` \| `"failed"` \| `"archived"` | Lifecycle state — maintained by your API, not derived from framework |
| `goal` | string | The user's original goal (for list display — no deserialisation needed) |
| `created_at` | ISO timestamp | Set once on creation |
| `updated_at` | ISO timestamp | Updated on every status change |

**What to NOT put in the registry:**

- Plan steps — those belong in the framework's checkpoint/state
- Message history — that belongs in `checkpoints` / `adk_events`
- Tool results — framework's job
- Any data that the framework already owns

The registry is deliberately thin — it is a **fast-query index**, not a copy of the framework's data.

---

### How It Solves the Existing Gaps

**Mode restoration on refresh:**
```javascript
// Frontend: load sessions on mount
const sessions = await api.listSessions(token);  // queries session_registry
// Each session already has mode — no deserialisation, no extra requests
const lastMode = sessions[0]?.mode || 'plan';
setMode(lastMode);
```

**Listing sessions without deserialising checkpoints:**
```python
# Before (current LangGraph approach) — O(n) deserialisations
thread_ids = db.checkpoints.distinct("thread_id")
for tid in thread_ids:
    state = await graph.aget_state({"configurable": {"thread_id": tid}})
    # ^^^^ deserialises msgpack blob for every session

# After (registry approach) — single O(1) query
sessions = list(db.session_registry.find({"user_id": user_id}).sort("updated_at", -1))
```

**Cross-framework session list:**
```python
# One query, both frameworks
db.session_registry.find({
    "user_id": user_id,
    "status": {"$ne": "archived"}
}).sort("updated_at", -1)
```

**Status sync — who updates `status`?**
Your API layer updates `session_registry.status` as the execution progresses. The framework doesn't touch the registry. Example flow for LangGraph plan mode:

```
POST /sessions           → write registry {status: "active"}
GET /plan (stream)       → SSE yields "plan_complete"   → update registry {status: "awaiting_approval"}
GET /execute (stream)    → SSE yields "completed"       → update registry {status: "completed", updated_at: now}
POST /sessions/{id}/stop → your handler                 → update registry {status: "archived"}
```

---

### Implementation Sketch

**1. Session creation (LangGraph, but identical for ADK):**

```python
async def create_session(goal: str, user_id: str, framework: str, mode: str) -> str:
    session_id = str(uuid.uuid4())

    # Write registry first — before touching the framework
    db.session_registry.insert_one({
        "_id": session_id,
        "user_id": user_id,
        "framework": framework,
        "mode": mode,
        "status": "active",
        "goal": goal[:200],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    })

    # Pass same ID to framework
    if framework == "langgraph":
        config = {"configurable": {"thread_id": session_id}}
        await graph.ainvoke(initial_state, config)
    elif framework == "adk":
        await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )

    return session_id
```

**2. List sessions (fast, no deserialisation):**

```python
def list_sessions(user_id: str) -> list:
    return list(
        db.session_registry
          .find({"user_id": user_id, "status": {"$ne": "archived"}})
          .sort("updated_at", -1)
          .limit(50)
    )
```

**3. Fetch framework detail when needed:**

```python
async def get_session_detail(session_id: str) -> dict:
    reg = db.session_registry.find_one({"_id": session_id})
    if not reg:
        raise HTTPException(404)

    if reg["framework"] == "langgraph":
        state = await graph.aget_state({"configurable": {"thread_id": session_id}})
        detail = state.values  # full AgentState
    else:
        session = await session_service.get_session(
            app_name=APP_NAME, user_id=reg["user_id"], session_id=session_id
        )
        detail = session.state

    return {**reg, "detail": detail}
```

The list endpoint hits only the registry (fast). The detail endpoint hits the framework only when a user opens a specific session.

---

### Chat Mode: Special Case

For LangGraph chat mode, the thread ID is `chat-{user_id}` — not a UUID. There is only one chat thread per user, not a list of sessions. The registry entry looks like:

```json
{
  "_id": "chat-user_demo",
  "user_id": "user_demo",
  "framework": "langgraph",
  "mode": "chat",
  "status": "active",
  "goal": null,
  "created_at": "2026-03-03T09:00:00Z",
  "updated_at": "2026-03-03T09:30:00Z"
}
```

This entry is upserted (not inserted) on each chat message — it is the singleton chat record for that user.

For ADK chat mode, each conversation is a real UUID session, so it gets a normal registry entry like any plan session.

---

### MongoDB Index Recommendations

```js
// Primary access pattern — list sessions for a user, newest first
db.session_registry.createIndex({ "user_id": 1, "updated_at": -1 })

// Filter by framework (for cross-framework dashboards)
db.session_registry.createIndex({ "user_id": 1, "framework": 1, "status": 1 })
```

---

### Summary

| | Without Registry | With Registry |
|---|---|---|
| List sessions | Deserialise N msgpack blobs | Single `find()` query |
| Mode on refresh | Lost on every refresh | Always in registry |
| Cross-framework list | Not possible | One collection, one query |
| Active session count | Count distinct thread_ids | `countDocuments({status: "active"})` |
| Session status | Derived from framework state | Explicit field, always accurate |
| Framework swap | Break all queries | Change `framework` field, query unchanged |
| Created-at timestamp | Buried in binary (LangGraph) | Always present, always indexed |

---

## 14. Long-running Task Resilience: SSE Disconnect Behaviour

The question: *if an agent is mid-execution and the user refreshes the page (SSE connection drops), what happens to the running task?*

The answer depends on the framework **and** which endpoint is serving the request.

---

### How execution is coupled to the HTTP connection

Both frameworks run execution code inside `async` generator functions consumed by FastAPI's `StreamingResponse`. The critical question is whether the task **dies** or **survives** when the client drops.

```
                  HTTP connection alive             HTTP connection dropped
                  ───────────────────────           ──────────────────────
FastAPI           consumes generator                stops consuming generator
async generator   yields events                     generator receives no more .send()
astream/run_async keeps executing (producer)        ??? ← this is the key question
```

**The answer**: asyncio does **not** automatically cancel a producer coroutine just because its consumer stops reading. Unless code explicitly checks for disconnection and raises `CancelledError`, execution keeps running.

---

### LangGraph — execution survives disconnect (all modes)

`stream_graph()`, `stream_session()`, and `chat_stream()` in `react_agent.py` all follow the same pattern — `self._graph.astream()` runs **inside** the async generator:

```python
async def stream_graph(self, session_id, initial_state, config):
    async for chunk in self._graph.astream(initial_state, config, stream_mode="updates"):
        # process chunk ...
        yield event   # ← FastAPI stops pulling here on disconnect
                      #   BUT astream() is not cancelled — it keeps going
```

When the client disconnects:
1. FastAPI stops pulling from the generator
2. `astream()` is still running — it continues executing graph nodes
3. `MongoDBSaver` writes a checkpoint after **every node completes**
4. The graph runs to completion (or errors), then the coroutine exits naturally

No explicit disconnect handling exists — no `request.is_disconnected()`, no `try/finally` cleanup, no `asyncio.create_task()`. Background execution is *accidental*: asyncio keeps the coroutine alive until it completes.

**After the user reconnects:**
```
GET /sessions/{session_id}         → reads latest checkpoint from MongoDB
GET /sessions/{session_id}/execute → resumes from latest checkpoint if not done
```

Because every node is checkpointed, the graph can resume exactly where it left off — or the user finds it already completed.

---

### ADK — behaviour depends on the endpoint type

**Chat mode (SSE — `POST /sessions/{id}/chat/stream`):**

`chat_stream()` yields events from `runner.run_async()` inside the SSE generator. When the client disconnects, FastAPI closes the generator, which propagates an exception **into** `runner.run_async()` and terminates it mid-turn:

```python
async def chat_stream(self, session_id, user_id, message, auth_token):
    async for event in self._chat_runner.run_async(...):
        yield event   # ← generator closed on disconnect
                      #   run_async() receives GeneratorExit → execution stops
```

- **Execution stops immediately**
- Partial turn is lost — `MongodbSessionService.append_event()` skips `partial=True` events, so nothing in-progress is saved to `adk_events`
- The last *fully completed* turn's events are preserved
- **User must resend the message to get a response**

**Plan mode (blocking HTTP — `POST /sessions/{id}/execute-all` and `execute-step`):**

These are regular `async def` endpoints returning a JSON body — **not SSE**. Client disconnect has zero effect on server execution:

```python
@router.post("/sessions/{session_id}/execute-all")
async def execute_all_steps_endpoint(session_id, ...):
    result = await adk_agent.execute_all_steps(session_id, auth_token=token)
    return result   # runs to completion regardless of whether client is still connected
```

- **Execution always completes** on the server
- Results saved to `adk_sessions.state` via `output_key` per step
- After reconnect: `GET /sessions/{id}` returns the full updated state with all step results

---

### Behaviour matrix

| Scenario | LangGraph | ADK |
|---|---|---|
| **Chat SSE — user refreshes mid-message** | Execution **continues**; last checkpoint preserved | Execution **stops** mid-turn; partial work lost |
| **Plan generation SSE — user refreshes** | Execution **continues**; all nodes checkpointed | N/A — plan uses blocking HTTP POST, not SSE |
| **Plan execution — user refreshes** | Execution **continues**; every step checkpointed | Execution **continues** (blocking HTTP); results saved |
| **Partial work preserved?** | ✅ Yes — per-node MongoDB checkpoints | ❌ Chat: No. ✅ Plan: Yes — per-step `adk_sessions.state` |
| **Reconnect & resume?** | ✅ `GET /sessions/{id}/execute` resumes from checkpoint | ✅ Plan: `GET /sessions/{id}` shows results. ❌ Chat: resend |
| **Disconnect detected?** | ❌ No — `request.is_disconnected()` not called | ❌ No |

---

### The production-grade approach

Current behaviour is workable but has two problems:

1. **Orphaned LangGraph executions** — if the user navigates away permanently, the graph keeps consuming Vertex AI quota with no listener.
2. **ADK chat is fragile** — a single network hiccup mid-message loses the entire turn.

**The fix: decouple execution from the HTTP connection.**

Execution should be a true background task. The SSE stream becomes a *status feed* that any client can subscribe to and re-subscribe to at any time:

```
Client                      FastAPI                    Background worker
  │                            │                              │
  │  POST /sessions/{id}/exec  │                              │
  │ ──────────────────────────►│  asyncio.create_task() ─────►│ runs pipeline
  │ ◄── 202 {status:"running"} │                              │ writes events
  │                            │                              │   to MongoDB
  │  GET /sessions/{id}/stream │                              │
  │ ──────────────────────────►│  tail MongoDB events ───────►│
  │ ◄══ SSE (progress) ════════│                              │
  │                            │                              │
  │  [user refreshes]          │                              │
  │                            │                              │
  │  GET /sessions/{id}/stream │                              │
  │ ──────────────────────────►│  replay from last_event_id ►│
  │ ◄══ SSE (resumes) ═════════│                              │
```

**Minimal implementation — `asyncio.create_task()` (same process):**

```python
# Task registry — maps session_id to running asyncio.Task
_running_tasks: dict[str, asyncio.Task] = {}

@router.post("/sessions/{session_id}/execute-all")
async def start_execution(session_id: str, ...):
    """Start pipeline in background — return immediately."""
    task = asyncio.create_task(
        adk_agent.execute_all_steps(session_id, auth_token=token)
    )
    _running_tasks[session_id] = task
    task.add_done_callback(lambda _: _running_tasks.pop(session_id, None))
    return {"status": "running", "session_id": session_id}

@router.get("/sessions/{session_id}/status")
async def get_status(session_id: str, ...):
    """Reconnect-safe status check — reads MongoDB, not the stream."""
    state = await adk_agent.get_session_state(session_id)
    return {**state, "is_running": session_id in _running_tasks}
```

**Scalability options:**

| Requirement | Solution |
|---|---|
| Task survives client disconnect | `asyncio.create_task()` — same process, immediate |
| Task survives server restart | ARQ + Redis, Celery, or similar task queue |
| SSE stream resumable from any point | Write events to MongoDB as they emit; SSE endpoint replays from `after_event_id` |
| Cancel a stuck task | `_running_tasks[session_id].cancel()` via a `DELETE /sessions/{id}/task` endpoint |
| Multiple server instances | Redis-backed task queue + shared MongoDB event log |

---

## 15. Implementing Long-running Tools

Tools that take minutes (PDF parsing, batch processing, external API jobs) need special handling so the agent doesn't block or time out waiting.

**Production pattern:** Submit work to a Celery queue, pause the agent immediately, let the worker complete in the background, then resume via a callback to a `/resume` endpoint.

---

### What happens to the SSE stream when a tool is submitted to Celery

The stream **closes cleanly** — it does not hang. Here is the exact sequence:

```
Client SSE stream               runner / graph              Celery worker
─────────────────────           ────────────────────        ──────────────────
stream open
                                agent calls tool()
                                  .delay() → Redis (~1ms)
                                  returns {pending, job_id}
                                framework detects long-running tool
                                yields interrupted event ──► client receives it
                                generator ENDS
stream closes naturally ◄───    SSE generator exhausted     task running...
                                                            task completes
                                                            POST /resume ◄───
new runner.run_async() ◄────────────────────────────────────────────────────
  invocation_id=saved_id
agent resumes
```

The Celery worker and the HTTP stream are completely decoupled from the moment `.delay()` is called. The only way to hang is if the tool function does blocking work before returning (e.g. calling `.get()` instead of `.delay()`).

---

### ADK — `LongRunningFunctionTool` + Celery

Three things needed:
1. Wrap the slow function with `LongRunningFunctionTool(fn)`
2. Enable `ResumabilityConfig` on the `App`
3. On the API side: start → store `invocation_id` → Celery worker completes → resume

```python
from celery import Celery
from google.adk.tools import LongRunningFunctionTool
from google.adk.apps import App, ResumabilityConfig
from google.adk.runners import Runner

celery_app = Celery("jobs", broker="redis://redis:6379/0", backend="redis://redis:6379/0")

# ── 1. Celery task — runs in a worker process ─────────────────────────────────
@celery_app.task
def parse_pdfs_task(files: list[str], session_id: str, user_id: str):
    """Worker: does the actual heavy lifting. Calls /resume when done."""
    result = _do_actual_pdf_parsing(files)   # blocking, takes minutes

    # Retrieve invocation_id that was saved when ADK paused the agent
    state = get_session_state(session_id)
    invocation_id = state["pending_invocation_id"]

    import httpx
    httpx.post(
        f"http://api/sessions/{session_id}/resume",
        json={"user_id": user_id, "result": result, "invocation_id": invocation_id},
    )

# ── 2. LongRunningFunctionTool function — just submits to queue ───────────────
async def parse_pdfs(files: list[str], auth_token: str) -> dict:
    """Submit to Celery queue. Returns pending immediately."""
    task = parse_pdfs_task.delay(files, session_id, user_id)   # ~1ms
    return {"status": "pending", "job_id": task.id}

parse_tool = LongRunningFunctionTool(parse_pdfs)
# Framework auto-appends to description: "NOTE: Do not call again if pending"

# ── 3. App with ResumabilityConfig ────────────────────────────────────────────
app = App(
    name="adk_demo",
    root_agent=LlmAgent(model=..., tools=[parse_tool]),
    resumability_config=ResumabilityConfig(is_resumable=True),
)
runner = Runner(app=app, session_service=session_service)
```

**API side — capture `invocation_id`, expose resume endpoint:**

```python
# chat_stream(): ADK pauses → save invocation_id so the Celery worker can find it
async for event in runner.run_async(...):
    if event.interrupted:
        _update_session_state(session_id, {
            "pending_invocation_id": event.invocation_id
        })
    yield event
# ← generator ends here; stream closes cleanly

# Worker POSTs here when job is done
@router.post("/sessions/{session_id}/resume")
async def resume_invocation(session_id: str, body: dict, ...):
    state = get_session_state(session_id)
    invocation_id = state["pending_invocation_id"]
    async for event in runner.run_async(
        user_id=body["user_id"],
        session_id=session_id,
        invocation_id=invocation_id,
        new_message=Content(role="tool", parts=[Part.from_text(json.dumps(body["result"]))]),
    ):
        ...  # collect or stream back to client (via WebSocket, push notification, etc.)
```

---

### LangGraph — `interrupt()` + `Command(resume=...)` + Celery

LangGraph has no `LongRunningFunctionTool` class. The equivalent is the **`interrupt()` + `Command(resume=...)` pattern** — the same mechanism already used for plan approval in this project. Only the trigger changes: instead of a user click, it's a Celery callback.

```python
from celery import Celery
from langgraph.types import interrupt, Command

celery_app = Celery("jobs", broker="redis://redis:6379/0", backend="redis://redis:6379/0")

# ── 1. Celery task — runs in a worker process ─────────────────────────────────
@celery_app.task
def parse_pdfs_task(files: list[str], session_id: str):
    """Worker: does actual work. Calls /resume when done."""
    result = _do_actual_pdf_parsing(files)

    import httpx
    httpx.post(
        f"http://api/sessions/{session_id}/resume",
        json={"result": result},
    )

# ── 2. Graph node — submits job and pauses ────────────────────────────────────
async def parse_pdfs_node(state: AgentState):
    files = state["files_to_parse"]
    session_id = state["session_id"]

    # Submit to Celery — returns immediately (~1ms)
    task = parse_pdfs_task.delay(files, session_id)

    # Pause graph here — full state checkpointed to MongoDB
    result = interrupt({"job_id": task.id, "status": "waiting"})
    # ^^^ resumes here when Command(resume=result) is called

    return {"parsed_data": result, "status": "parsing_complete"}
```

**Wire into the graph:**

```python
builder = StateGraph(AgentState)
builder.add_node("parse_pdfs", parse_pdfs_node)
builder.add_edge("dispatch", "parse_pdfs")
builder.add_edge("parse_pdfs", "next_step")

graph = builder.compile(
    checkpointer=MongoDBSaver(...),
    # parse_pdfs node auto-interrupts via interrupt() — no extra config needed
)
```

**API side — resume endpoint (identical pattern to plan approval):**

```python
# Worker POSTs here when job is done
@router.post("/sessions/{session_id}/resume")
async def resume_graph(session_id: str, body: dict, ...):
    config = {"configurable": {"thread_id": session_id}}
    await graph.ainvoke(Command(resume=body["result"]), config)
    return {"status": "resumed"}
```

**Why this is identical to plan approval:**

```
# Plan approval (already in project):
#   user approves → graph.ainvoke(Command(resume={"approved": True}), config)

# Long-running tool:
#   Celery worker done → graph.ainvoke(Command(resume=job_result), config)
```

Same API call. Only the trigger differs.

---

### What the client sees on the stream

```
event: tool_call    → {"tool": "parse_pdfs", "args": {"files": [...]}}
event: tool_result  → {"status": "pending", "job_id": "abc123"}
event: interrupted  → {"invocation_id": "xyz", "pending": true}   ← ADK only
[stream closes]
```

The client must detect the interrupted/pending state and either:
- Poll `GET /sessions/{id}/status` until the Celery callback fires
- Or receive a push notification (WebSocket, FCM, etc.) when the worker calls `/resume`

---

### Comparison

| | ADK | LangGraph |
|---|---|---|
| **Pause mechanism** | `LongRunningFunctionTool` — tool returns pending, framework pauses | `interrupt()` inside node — explicit pause point |
| **Enable** | `App(resumability_config=ResumabilityConfig(is_resumable=True))` | Already enabled via `MongoDBSaver` checkpointer |
| **State saved by** | `ResumabilityConfig` stores invocation state | `MongoDBSaver` — same durability as plan approval |
| **Celery task sends** | `session_id` → worker looks up stored `invocation_id` from session state | `session_id` directly — no extra lookup needed |
| **Resume call** | `runner.run_async(invocation_id=..., new_message=result)` | `graph.ainvoke(Command(resume=result), config)` |
| **SSE stream on submit** | Closes cleanly after `event.interrupted` | Closes cleanly after `interrupt()` event |
| **Already in project?** | Not yet | Partially — `interrupt()` used for plan approval; same resume API |
| **Celery already in project?** | No — add `celery[redis]` dep if Redis infra exists | No — same |

---

## 16. How MCP Requests Are Authenticated

The token travels from the user's browser to the MCP server via two different mechanisms depending on which framework is in play.

---

### LangGraph — token via HTTP header (clean path)

The token is injected once at client creation and carried as an `Authorization: Bearer` header on every MCP request automatically.

```
User JWT
  │
  ▼
create_mcp_client(token)                    ← app/mcp/client.py:21
  MultiServerMCPClient({
    "main": {
      "transport": "streamable_http",
      "url": ".../mcp",
      "headers": {"Authorization": "Bearer <jwt>"}   ← injected here
    }
  })
  │
  │  every MCP request carries the header
  ▼
MCP Server /mcp (FastMCP streamable-http)
  _get_auth_token(ctx)                      ← mcp-server/src/server.py:28
    request = get_http_request()            ← FastMCP pulls the Starlette request
    return request.headers["authorization"][7:]   ← strips "Bearer "
  │
  ▼
Backend API  ← validates JWT on every call; MCP server does NO independent validation
```

---

### ADK — token via LLM instruction (workaround)

ADK's `MCPToolset` / `StreamableHTTPConnectionParams` has no `headers=` parameter. The token cannot be injected at connection time. Instead it travels through the LLM's prompt:

```
User JWT
  │
  ▼
chat_stream() / _build_step_instruction()   ← adk_agent.py:346, 709
  full_message = f'[System context: use auth_token="{auth_token}" for all tool calls]'
  │
  │  LLM reads instruction, includes auth_token in every tool call argument
  ▼
LlmAgent → tools/call:
  {"name": "list_items", "arguments": {"auth_token": "<jwt>", skip: 0, limit: 100}}
                                          ↑ regular tool parameter
  │
  ▼
MCP Server /mcp
  _extract_token_from_context(ctx) or auth_token   ← adk/mcp-server/src/server.py:99
  (header attempt fails → falls back to auth_token argument)
  │
  ▼
Backend API
```

The `/message` JSON-RPC endpoint (used by plan mode direct calls) adds an extra validation step: it calls `GET /auth/me` against the backend before proceeding (`validate_token()` in `adk/mcp-server/src/app.py:76`). The native `/mcp` streamable-http endpoint does not — it relies on the backend to reject invalid tokens.

---

### Side-by-side comparison

| | LangGraph | ADK |
|---|---|---|
| **Token transport to MCP** | HTTP `Authorization: Bearer` header — set once at client creation | Tool argument `auth_token=<jwt>` — LLM passes it in every call |
| **Who injects the token** | `create_mcp_client(token)` in `client.py` | `chat_stream()` / `_build_step_instruction()` prepend it into the prompt |
| **MCP server extraction** | `request.headers.get("authorization")` via FastMCP `get_http_request()` | `_extract_token_from_context(ctx) or auth_token` — header first, param fallback |
| **Token validation in MCP layer** | None — backend validates on every API call | `/message` endpoint calls `GET /auth/me` upfront; native `/mcp` delegates to backend |
| **Risk** | Clean — token never visible to LLM | Token appears in LLM context and potentially in logs; LLM could omit it |
| **Why the difference** | `MultiServerMCPClient` accepts `headers=` | `MCPToolset`/`StreamableHTTPConnectionParams` has no `headers=` param |

---

## 17. Token Generation from User Identity

### The problem

Agent tasks and MCP tool calls need a valid JWT. Using the user's login token directly has a key weakness: login tokens expire (30-minute default), and a long-running session — or a resumed Celery task — will hit a 401 mid-execution.

### How the POC solves it

**Mechanism: server-side token minting without credentials**

The backend holds a secret key and can sign a JWT for any user identity it already knows about. No password is needed — the server trusts itself:

```
Normal login:
  credentials → verify against DB → mint token

Internal token generation:
  user_id + role → (skip credential check) → mint token
                        ↑
              trusted because the call is server-side
```

**`create_mcp_token()` — fresh token per API action** ([app/auth/authorization.py:179](app/auth/authorization.py#L179))

```python
async def create_mcp_token(user: TokenData, expires_minutes: int = 60) -> str:
    return create_access_token(
        user_id=user.user_id,
        username=user.username,
        role=user.role,
        expires_delta=timedelta(minutes=expires_minutes)
    )
```

Called at every user-triggered action — session create, plan approval, replan, retry. A fresh 60-minute token is minted from the validated `current_user` each time, then embedded in the graph state / agent instruction for that execution window.

```python
# streaming.py:80, agent_routes.py:62, 281, 361
mcp_token = await create_mcp_token(current_user)   # fresh 60-min token
session_id = orchestrator.create_session(..., token=mcp_token)
```

**`POST /auth/token/generate` — programmatic token from user_id** ([app/api/auth_routes.py:89](app/api/auth_routes.py#L89))

```python
@router.post("/token/generate")   # ← no Depends(get_current_user) — unprotected
async def generate_token(request: TokenRequest):
    # TokenRequest: user_id, username, role, expires_minutes
    return await authorization_tool.generate_user_token(...)
```

Intended for internal services (Celery workers, background tasks) that need a token without a user session. No existing token or password required — just a `user_id`, `username`, and `role`.

**Token expiry settings:**

| Token | Default expiry | Configured in |
|---|---|---|
| User login token | 30 min | `JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30` in `.env` / `docker-compose.yml` |
| MCP / agent token | 60 min | `create_mcp_token(expires_minutes=60)` default |
| Token blacklist TTL | 3600 sec | `revoke_token(ttl_seconds=3600)` |

**The remaining gap:** the `mcp_token` is embedded in graph state at session creation time. If execution is paused (user approval, Celery task) and resumed after 60 minutes, the stored token is expired. The fix is to mint a fresh token at each resume/execute interaction — the same pattern already used for approval and replan endpoints.

---

### Does this pattern work with Django and AWS Cognito?

#### Django — yes, maps directly

Django's user model is just a database record. JWT minting is framework-agnostic. The same pattern works:

```python
from django.contrib.auth.models import User
import jwt
from datetime import datetime, timedelta

def generate_token_for_user(user: User, expires_minutes=60) -> str:
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": get_user_role(user),   # your own group/flag mapping
        "exp": datetime.utcnow() + timedelta(minutes=expires_minutes),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

# From a Celery task or internal endpoint:
user = User.objects.get(id=user_id)
token = generate_token_for_user(user, expires_minutes=120)
```

If using **`djangorestframework-simplejwt`**, it already has a built-in equivalent:

```python
from rest_framework_simplejwt.tokens import RefreshToken

# No password needed — just a User object
refresh = RefreshToken.for_user(user)
access_token = str(refresh.access_token)
```

`RefreshToken.for_user(user)` is the Django equivalent of `create_mcp_token()`. It's a standard pattern used in Django for SSO callbacks, email verification tokens, agent tasks, and any server-initiated token generation.

---

#### AWS Cognito — fundamentally different; pattern does NOT transfer directly

The POC uses **symmetric JWT (HS256)** — one shared secret, server signs and verifies. Cognito uses **asymmetric JWT (RS256)** — Cognito holds the private key, you only get the public key.

```
POC / Django (HS256):            AWS Cognito (RS256):
─────────────────────────        ──────────────────────────────────
One secret key                   RSA key pair; private key stays in Cognito
Anyone with secret can sign      Only Cognito's servers can sign
You control claims & expiry      Cognito controls token structure
```

**You cannot mint a Cognito-signed token from user_id.** Cognito's public key is at `cognito-idp.{region}.amazonaws.com/{pool}/.well-known/jwks.json` but the private key never leaves AWS.

**Options with Cognito:**

| Approach | How | Tradeoff |
|---|---|---|
| **`AdminInitiateAuth`** | Server-side login with `ADMIN_USER_PASSWORD_AUTH` flow — returns Cognito tokens without browser redirect | Needs user password stored server-side |
| **Store refresh token** | At login, store Cognito's 30-day refresh token in MongoDB; exchange for fresh access token before each task | Refresh tokens are sensitive; revocation risk if leaked |
| **Client Credentials flow** | Machine-to-machine OAuth2 — returns a service token, not user-scoped | Loses user identity in the token |
| **Hybrid internal JWT** | Cognito handles user-facing auth; at the API boundary extract `sub` (Cognito user_id) and mint your own HS256 token for internal service calls | Two auth systems to maintain, but solves the problem cleanly |

**Recommended for Cognito — hybrid approach:**

```
Browser ──► API Gateway ──► [validate Cognito token, extract sub]
                                         │
                                         ▼
                               your backend mints internal HS256 JWT
                               using sub (Cognito user_id) + role from your DB
                                         │
                                Celery worker / MCP call / agent task
```

This is identical to what the POC does — Cognito just handles the initial user-facing authentication, and your backend takes over for the internal service layer.

---

### Summary

| | HS256 (this POC) | Django simplejwt | AWS Cognito |
|---|---|---|---|
| **Mint token from user_id?** | Yes — sign with secret | Yes — `RefreshToken.for_user(user)` | No — only Cognito can sign Cognito tokens |
| **No credentials needed?** | Yes | Yes | No (need password or refresh token) |
| **Token lives where?** | Your server | Your server | Cognito (external) |
| **Pattern for agent tasks** | `create_mcp_token()` fresh per action | `RefreshToken.for_user(user)` at task start | Store refresh token and exchange; or hybrid internal JWT |
