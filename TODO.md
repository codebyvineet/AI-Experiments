# TODO — Execution Resilience

> **Status:** Planned — not yet implemented  
> **Priority:** Phase 1 is next after current feature work completes

When an AI agent is executing a plan (multiple steps), several things can go wrong:
- User refreshes the page mid-execution
- User closes the tab
- Network drops
- Server crashes/restarts
- A single step takes a very long time (30+ min)

This document captures the research findings and phased implementation plan.

---

## Current Behavior Summary

| Scenario | Google ADK | LangGraph |
|----------|-----------|-----------|
| **User refreshes** | POST handler keeps running (FastAPI doesn't cancel). No per-step writes — all show "in_progress" until done. | Same, but MongoDBSaver checkpoints per-node. |
| **User closes tab** | Same as refresh — handler completes, writes results. | Same. |
| **Server crashes** | 🔴 Steps stuck as "in_progress" forever. No recovery. | ✅ Resume from checkpoint. |
| **Network drops** | TCP stays alive briefly. Handler likely completes. | Same. |
| **SSE stream drops** | Generator cancelled. In-flight response lost. | Same. |
| **Long-running tool (30+ min)** | 🔴 Blocks entire pipeline while waiting. | 🔴 Same. |

**Key insight:** Execution keeps running on disconnect (FastAPI POST handlers are NOT cancelled). The problem is a **notification gap** — the frontend doesn't know when results are ready.

---

## Phase 1: Background Pipeline + SSE via Redis Pub/Sub

Make plan execution survive page refreshes with real-time push — **no polling**.

### Google ADK (`google-adk/`)

- [ ] **adk-background-execute** — Refactor `execute_all_steps()` to run via `asyncio.create_task()`. Write per-step results to MongoDB as each completes. Publish events to Redis Pub/Sub channel `execution:{session_id}`. Return 202 + execution_id.
- [ ] **adk-sse-stream** — Add `GET /agent/sessions/{id}/execute-stream` SSE endpoint. Subscribe to Redis channel. On connect, send catch-up from MongoDB first, then stream live events. Handle duplicate filtering.
- [ ] **adk-frontend-sse** — Refactor `handleExecuteAll()`: POST → 202 → connect `EventSource` to `/execute-stream` → render steps as events arrive → store execution_id in sessionStorage → on refresh, reconnect SSE (catch-up from MongoDB).
- [ ] **adk-session-recovery** — On `loadSession()`, check if execution is running → auto-connect SSE stream for remaining events.
- [ ] **adk-stale-detection** — Detect stale `running` executions (>10 min no progress). Allow retry/cancel.

### LangGraph (`app/`)

- [ ] **lg-background-execute** — Same `asyncio.create_task()` + Redis Pub/Sub pattern. LangGraph checkpoints per-node via MongoDBSaver.
- [ ] **lg-sse-stream** — Same SSE endpoint with Redis subscription + MongoDB catch-up.
- [ ] **lg-frontend-sse** — Same frontend EventSource pattern (shared logic with ADK).

### Frontend Pattern

```javascript
// Start execution — returns 202 immediately
const { execution_id } = await fetch('/execute-all', { method: 'POST' });
sessionStorage.setItem('execution_id', execution_id);

// Connect SSE — real-time push via Redis Pub/Sub, no polling
const source = new EventSource(`/execute-stream/${sessionId}`);
source.onmessage = (e) => {
    const event = JSON.parse(e.data);
    if (event.type === 'step_complete') updateStepUI(event);
    if (event.type === 'execution_done') source.close();
};

// On page load — check if execution was in progress
if (sessionStorage.getItem('execution_id')) {
    // Reconnect SSE — server sends catch-up from MongoDB, then live from Redis
    connectExecuteStream(sessionId);
}
```

---

## Phase 2: Celery for Long-Running Tools (implement when needed)

For tools that take 30+ minutes (PDF parsing, data processing):

```
Agent → calls MCP tool → MCP submits to Celery → returns task_id → Agent PAUSES
                                                                          ↓
Celery Worker processes 10GB PDF → completes → result in MongoDB
                                                                          ↓
Backend polls Celery → done! → sends FunctionResponse → Agent RESUMES
```

- [ ] **celery-setup** — Add Celery worker container to docker-compose. Broker: Redis (already running). Result backend: MongoDB (already running).
- [ ] **mcp-celery-tools** — MCP tools submit long-running work to Celery, return task_id.
- [ ] **adk-long-running-tool** — Wrap Celery-backed MCP tools with `LongRunningFunctionTool`.
- [ ] **lg-interrupt-resume** — Wrap Celery-backed tools with `interrupt()` + `Command(resume=result)`.

### docker-compose.yml additions

```yaml
celery-worker:
    build: ./mcp-server
    command: celery -A tasks worker --loglevel=info
    depends_on: [redis, mongodb]
```

---

## Shared

- [ ] **test-refresh-resilience** — Playwright: start execution → refresh mid-flight → verify SSE reconnects → results appear.
- [ ] **update-docs** — Document background execution + SSE + Redis Pub/Sub + Celery architecture.

---

## Architecture Notes

- **Redis Pub/Sub** is the real-time notification layer — instant, no polling
- **MongoDB** is the durable store — catch-up on reconnect, survives crashes
- `asyncio.create_task` is sufficient for single-process Docker deployment
- Celery uses Redis as broker (already running) + MongoDB as result backend — **no new infrastructure**
- ADK `LongRunningFunctionTool` + Celery is a natural fit: framework manages pause/poll/resume, Celery does the work
- LangGraph equivalent: `interrupt()` + `Command(resume=...)` + MongoDBSaver for crash recovery
- Frontend uses `sessionStorage` for execution_id (survives refresh, clears on tab close)
- `EventSource` (browser built-in) auto-reconnects — SSE endpoint handles catch-up transparently

---

## Research Sources

- [FastAPI Discussion #8805](https://github.com/fastapi/fastapi/discussions/8805) — POST handlers NOT cancelled on disconnect
- [FastAPI Expert Blog](https://fastapiexpert.com/blog/2024/06/06/understanding-client-disconnection-in-fastapi/) — SSE generators DO get cancelled
- [Python asyncio docs](https://docs.python.org/3.11/library/asyncio-task.html) — `create_task()` tasks survive parent cancellation
- [ADK Workflow Agents](https://google.github.io/adk-docs/agents/workflow-agents/) — ParallelAgent/SequentialAgent
- [ADK LongRunningFunctionTool](https://google.github.io/adk-docs/tools/) — pause/poll/resume pattern
