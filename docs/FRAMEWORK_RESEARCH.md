# Framework Research: Code Reduction Opportunities

> Research conducted March 2026. Evaluating popular frameworks that could reduce custom code
> while maintaining the same functionality (MCP Server, LangGraph orchestration, RBAC,
> checkpointing, chat mode, plan mode).

---

## Current Codebase Metrics

| Component | Lines | Composition |
|-----------|-------|-------------|
| Agent (graph, nodes, state, react_agent, ai_service, checkpointer) | ~1,570 | 45% custom, 45% glue, 10% framework |
| API Routes (streaming, auth, items, agent, mcp) | ~1,340 | 15% framework, 85% glue |
| Auth / MCP Client | ~497 | 50% custom, 50% glue |
| MCP Server (standalone container) | ~568 | 60% framework, 40% glue |
| **Total backend** | **~4,000** | **~45% custom, ~45% glue, ~10% pure framework** |

**Key insight**: The codebase is heavily glue-heavy — orchestrating multiple frameworks (LangGraph, FastAPI, MCP, Vertex AI) rather than building from scratch. The custom code focuses on orchestration logic and AI prompting.

---

## Framework-by-Framework Analysis

### 🥇 Google ADK (Agent Development Kit) — Best Fit for Gemini Stack

**Why**: Built by Google specifically for Gemini users. Provides native MCP support, built-in REST/SSE server, human-in-the-loop, and session persistence.

| Feature | Status |
|---------|--------|
| MCP Support | ✅ **Built-in, first-class** — native `MCPToolset` class |
| Checkpointing | ✅ Session state management, persistent memory across turns |
| Human-in-the-loop | ✅ Built-in `require_confirmation` flag on tools |
| REST API / SSE | ✅ **Built-in FastAPI server** — `adk api_server` command |
| Gemini Support | ✅ **First-party** — native Vertex AI / Gemini integration |
| Multi-agent | ✅ Hierarchical agent delegation, parallel/sequential/loop |

**Code reduction estimate**: ~60-70% of orchestration code

| Current Custom Code | ADK Replacement | Lines Saved |
|---|---|---|
| `graph.py` (882 lines) — LangGraph StateGraph | ADK agent declarations + delegation | ~600 |
| `nodes.py` (429 lines) — node implementations | ADK `LlmAgent` + sub-agents | ~250 |
| `state.py` (95 lines) — TypedDict state | ADK session state (built-in) | ~75 |
| `mcp/client.py` (241 lines) — MCP client wrapper | ADK `MCPToolset` (one-liner) | ~230 |
| `main.py` + routes (~500 lines) — FastAPI setup | `adk api_server` (built-in) | ~400 |
| `streaming.py` (517 lines) — SSE endpoints | ADK built-in streaming | ~400 |
| `checkpointer.py` (399 lines) — dual checkpoint | ADK session persistence | ~300 |
| **Total** | | **~2,250 lines** |

```python
# Google ADK — complete agent with MCP tools in ~10 lines
from google.adk.agents import LlmAgent
from google.adk.tools.mcp import MCPToolset

agent = LlmAgent(
    name="task_executor",
    model="gemini-2.0-flash",
    instruction="You are a helpful assistant...",
    tools=[MCPToolset(server_url="http://mcp-server:8001/mcp")],
)
# MCP server remains standalone — ADK connects to it as a client
```

**Key advantage**: ADK replaces the need for:
- `langchain-mcp-adapters` → ADK has native `MCPToolset`
- Custom FastAPI endpoints → ADK has `adk api_server` / `adk web`
- LangGraph StateGraph boilerplate → ADK uses code-driven delegation patterns
- Custom checkpointer → ADK has built-in session/state persistence

**Risks**:
- Less mature than LangGraph — fewer community examples, some rough edges
- Less explicit graph control — if you need precise state management
- Vendor alignment — ties you closer to Google Cloud

**Sources**: [Google ADK Docs](https://google.github.io/adk-docs/mcp/), [Google Blog](https://developers.googleblog.com/en/agent-development-kit-easy-to-build-multi-agent-applications/), [ZenML Comparison](https://www.zenml.io/blog/google-adk-vs-langgraph)

---

### 🥈 CrewAI — Lowest Boilerplate

**Why**: Declarative agent definitions, built-in HITL, MCP toolbox. Best for rapid prototyping.

| Feature | Support |
|---------|---------|
| MCP | ✅ via `crewai-mcp-toolbox` — auto-discovers tools from MCP servers |
| Checkpointing | ✅ built-in execution state persistence |
| Human-in-the-loop | ✅ `human_input=True` on tasks, webhook-based approval |
| REST/SSE server | ❌ still need FastAPI or similar |
| Gemini | ✅ model-agnostic |
| Multi-agent | ✅ Role-based crews with delegation |

**Code reduction estimate**: ~40-50%

```python
# CrewAI — multi-agent crew in ~15 lines
from crewai import Agent, Task, Crew

planner = Agent(role="Planner", goal="Break down tasks", tools=[...])
executor = Agent(role="Executor", goal="Execute tasks", tools=[...])

plan_task = Task(description="Plan the work", agent=planner)
exec_task = Task(description="Execute the plan", agent=executor, human_input=True)

crew = Crew(agents=[planner, executor], tasks=[plan_task, exec_task])
result = crew.kickoff()
# MCP server remains standalone — CrewAI connects via crewai-mcp-toolbox
```

**Limitations**:
- Less fine-grained control — our `Send()` for parallel dispatch and `interrupt()` patterns harder to express
- Still needs FastAPI for REST endpoints and frontend SSE streaming
- YAML-based config can be limiting for complex workflows

**Sources**: [CrewAI Docs](https://docs.crewai.com/en/learn/human-in-the-loop), [crewai-mcp-toolbox](https://pypi.org/project/crewai-mcp-toolbox/)

---

### 🥉 OpenAI Agents SDK — Minimal Code, But Wrong Model

| Feature | Status |
|---------|--------|
| MCP | ✅ **First-class** — `mcp_servers=[...]` on agent |
| Checkpointing | ⚠️ Limited — traces & logging, no persistent checkpointing |
| Human-in-the-loop | ⚠️ Basic via Guardrails, no interrupt-style approval |
| REST/SSE | ❌ Not built-in |
| Gemini | ❌ **OpenAI models only** |
| Multi-agent | ✅ Via Handoffs between agents |

**Code reduction**: ~30% — great MCP integration, but you lose Gemini.

**Disqualifier**: Locked to OpenAI models. We use Gemini/Vertex AI.

**Sources**: [OpenAI MCP Docs](https://openai.github.io/openai-agents-python/mcp/)

---

### Microsoft AutoGen v0.4 — Conversation-Based

| Feature | Status |
|---------|--------|
| MCP | ✅ Via `McpWorkbench` extension |
| Checkpointing | ✅ Serializable agent states |
| Human-in-the-loop | ✅ Mid-execution via Studio UI |
| REST/SSE | ⚠️ Via AutoGen Studio (no-code UI) |
| Gemini | ✅ Model-agnostic |
| Multi-agent | ✅ Group chat orchestration |

**Code reduction**: ~20-30% — different paradigm (conversation-driven vs graph-based), significant rewrite.

**Not ideal**: Our structured plan→approve→execute workflow doesn't map well to conversation-based orchestration.

**Sources**: [AutoGen Docs](https://microsoft.github.io/autogen/stable/index.html)

---

### Microsoft Semantic Kernel — Enterprise-Grade

| Feature | Status |
|---------|--------|
| MCP | ✅ First-class client and server |
| Checkpointing | ✅ Agent checkpointing |
| Human-in-the-loop | ✅ Via orchestration patterns |
| REST/SSE | ⚠️ Not built-in |
| Gemini | ✅ Model-agnostic |
| Multi-agent | ✅ Multiple patterns |

**Code reduction**: ~15-25% — heavyweight framework, more enterprise boilerplate, not less.

**Sources**: [SK MCP Blog](https://devblogs.microsoft.com/semantic-kernel/semantic-kernel-adds-model-context-protocol-mcp-support-for-python/)

---

### Agno (formerly Phi-data) — Ultra-Lightweight

| Feature | Status |
|---------|--------|
| MCP | ✅ First-class |
| Checkpointing | ⚠️ Basic session memory |
| Human-in-the-loop | ⚠️ Limited |
| REST/SSE | ❌ Not built-in |
| Gemini | ✅ Model-agnostic |

**Code reduction**: ~25-35% — agent creation is minimal but need to rebuild HITL.

**Key stat**: Agent instantiation is ~10,000x faster than LangGraph (2μs per agent).

**Sources**: [ZenML comparison](https://www.zenml.io/blog/agno-vs-langgraph)

---

## Complete Feature Comparison Matrix

| Feature | LangGraph (current) | Google ADK | CrewAI | OpenAI SDK | AutoGen | Semantic Kernel | Agno |
|---|---|---|---|---|---|---|---|
| **Built-in MCP** | ❌ (adapters) | ✅ native | ✅ toolbox | ✅ native | ✅ workbench | ✅ | ✅ |
| **Built-in REST/SSE** | ❌ | ✅ | ❌ | ❌ | ⚠️ Studio | ❌ | ❌ |
| **Checkpointing** | ✅ MongoDB/Redis | ✅ session | ✅ | ⚠️ limited | ✅ | ✅ | ⚠️ |
| **Human-in-the-loop** | ✅ interrupt() | ✅ confirmation | ✅ human_input | ⚠️ guardrails | ✅ | ✅ | ⚠️ |
| **Gemini native** | ❌ (LangChain) | ✅ **first-party** | ✅ generic | ❌ OpenAI only | ✅ generic | ✅ generic | ✅ generic |
| **Graph control** | ✅ **explicit** | ⚠️ code-based | ❌ role-based | ❌ | ❌ chat | ✅ patterns | ❌ |
| **Boilerplate** | High | **Low** | **Lowest** | Low | Medium | High | **Lowest** |
| **Maturity** | High | Medium | High | Medium | High | High | Medium |

---

## MCP Ecosystem Findings

### FastMCP vs Official `mcp` SDK

| | Official `mcp` SDK | FastMCP 2.0/3.0 |
|---|---|---|
| **Maintainer** | Anthropic / MCP spec team | Jlowin (community, very active) |
| **API style** | Lower-level, explicit | High-level decorators, Pythonic |
| **Auth built-in** | Basic OAuth 2.1 | Full auth, RBAC helpers, proxy |
| **FastAPI integration** | None | `FastMCP.from_fastapi()`, ASGI mount |
| **Server composition** | Manual | `mount()`, proxy, transform, filter |
| **Recommendation** | Compliance-critical | **Most projects** (consensus pick) |

FastMCP 1.0 was merged into the official `mcp` SDK, then forked back out as FastMCP 2.0+ with enterprise features. We use FastMCP 3.0.2 — this is the right choice.

### All Major Frameworks Now Support MCP

MCP has become the de facto standard for tool calling in 2025:
- **Google ADK**: Native `MCPToolset` class
- **OpenAI SDK**: `mcp_servers=[...]` parameter
- **CrewAI**: `crewai-mcp-toolbox` auto-discovery
- **AutoGen**: `McpWorkbench` extension
- **Semantic Kernel**: Client + server mode

**Important**: The frameworks eliminate the *client-side adapter code*. You still need a standalone MCP server to host the tools.

### MCP Auth is Aligned with Our Approach

The MCP spec mandates OAuth 2.1 for HTTP transports but delegates RBAC to token claims — exactly what we do with JWT + role permissions. No change needed.

### Legacy SSE is Deprecated

The MCP protocol deprecated the dual `/sse` + `/messages` pattern in favor of **Streamable HTTP** (single `/mcp` endpoint). We already support this via FastMCP's `http_app()`.

### `langchain-mcp-adapters` Still Recommended

For LangChain/LangGraph, `langchain-mcp-adapters` remains the official bridge. Actively maintained by the LangChain team. No better alternative.

---

## Recommendation

| Approach | Risk | Code Reduction | When |
|---|---|---|---|
| **Migrate to Google ADK** | Medium | ~60-70% | When ADK matures (6-12 months) |
| **Switch to CrewAI** | Medium | ~40-50% | Anytime (mature) |
| **Stay with LangGraph** | Low | 0% | Current (stable) |

### Primary: Google ADK (when ready)
- Best fit for Gemini stack
- Eliminates most glue code
- MCP server stays standalone — ADK connects as client
- Wait for ecosystem maturity

### Alternative: CrewAI (if need faster migration)
- Most mature alternative
- Role-based agents map well to plan→execute pattern
- MCP server stays standalone — CrewAI connects via toolbox

### Not Recommended
- **OpenAI Agents SDK** — locked to OpenAI models
- **AutoGen** — different paradigm (conversation vs workflow)
- **Semantic Kernel** — enterprise overhead, no net reduction

### MCP Server Architecture: Keep Standalone
The MCP server MUST remain a separate container:
- Clean separation of concerns (tool hosting vs orchestration)
- Independent scaling
- Security boundary (tools don't have direct DB access)
- All frameworks support connecting to standalone MCP servers as clients

---

## Sources

| Topic | Source |
|-------|--------|
| Google ADK + MCP | https://google.github.io/adk-docs/mcp/ |
| Google ADK vs LangGraph | https://www.zenml.io/blog/google-adk-vs-langgraph |
| CrewAI HITL | https://docs.crewai.com/en/learn/human-in-the-loop |
| CrewAI MCP Toolbox | https://pypi.org/project/crewai-mcp-toolbox/ |
| OpenAI Agents SDK MCP | https://openai.github.io/openai-agents-python/mcp/ |
| AutoGen v0.4 | https://microsoft.github.io/autogen/stable/index.html |
| Semantic Kernel MCP | https://devblogs.microsoft.com/semantic-kernel/semantic-kernel-adds-model-context-protocol-mcp-support-for-python/ |
| Agno vs LangGraph | https://www.zenml.io/blog/agno-vs-langgraph |
| 12 Framework Comparison | https://clickhouse.com/blog/how-to-build-ai-agents-mcp-12-frameworks |
| FastMCP vs SDK | https://github.com/modelcontextprotocol/python-sdk/issues/1068 |
| MCP Auth Spec | https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization |
| MCP Streaming (Streamable HTTP) | https://blog.fka.dev/blog/2025-06-06-why-mcp-deprecated-sse-and-go-with-streamable-http/ |
| langchain-mcp-adapters | https://github.com/langchain-ai/langchain-mcp-adapters |
