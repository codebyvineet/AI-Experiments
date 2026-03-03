"""Google ADK agent implementation — replaces the custom LangGraph agent.

Architecture
------------
Two operating modes share the same ADK ``Runner`` and MongoDB-backed session store:

Chat mode  — a single ``LlmAgent`` with MCP tools executes ReAct-style
             tool calls in one turn.

Plan mode  — a two-phase workflow:
               1. Planner ``LlmAgent``  – generates a JSON plan of steps.
               2. Executor ``LlmAgent`` – carries out each step one at a time
                  using MCP tools, called via the chat runner.

Session State Strategy
----------------------
Uses ``MongodbSessionService`` from the ``adk-mongodb-session`` package for
**persistent** session storage.  This is analogous to LangGraph's
``MongoDBSaver`` checkpointer — all conversation history (events), session
state (plan, mode, steps), and metadata are stored in MongoDB automatically
by the framework.

- Chat history (messages, tool calls, tool results) survives app restarts
- Plan progress (steps, current_step, is_complete) persists in session state
- Session listing uses the framework's ``list_sessions()`` method

MCP tools are fetched from the standalone MCP server at startup via
``MCPToolset`` so the server stays completely independent.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.tools.mcp_tool import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.genai.types import Content, Part

from adk_mongodb_session.mongodb.sessions.mongodb_session_service import (
    MongodbSessionService,
)

from app.config import get_settings

settings = get_settings()
_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Compatibility patch for adk-mongodb-session vs google-adk 1.24.x
# The package calls _session_util.decode_content and decode_grounding_metadata
# which don't exist yet in this ADK version.  Inject simple pass-through stubs.
# ---------------------------------------------------------------------------
def _patch_session_util() -> None:
    import google.adk.sessions._session_util as _su

    if not hasattr(_su, "decode_content"):
        from google.genai.types import Content

        def _decode_content(data):
            if data is None:
                return None
            if isinstance(data, Content):
                return data
            try:
                return Content.model_validate(data)
            except Exception:
                return data

        _su.decode_content = _decode_content

    if not hasattr(_su, "decode_grounding_metadata"):
        from google.genai.types import GroundingMetadata

        def _decode_grounding_metadata(data):
            if data is None:
                return None
            if isinstance(data, GroundingMetadata):
                return data
            try:
                return GroundingMetadata.model_validate(data)
            except Exception:
                return data

        _su.decode_grounding_metadata = _decode_grounding_metadata


_patch_session_util()


# ---------------------------------------------------------------------------
# ADK agents
# ---------------------------------------------------------------------------

_CHAT_INSTRUCTION = """You are a helpful AI assistant with access to tools for
managing items (create, read, update, delete, list). Use the available tools to
fulfil user requests accurately. Always confirm actions you have taken.

IMPORTANT: When calling any tool, you MUST pass the auth_token parameter.
The auth_token will be provided to you in the user message context.
Always include auth_token in every tool call."""

_PLANNER_INSTRUCTION = """You are a planning agent. Given a user goal, produce
a JSON execution plan as a list of steps.

You have access to MCP tools \u2014 use their EXACT names in your plan.
Do NOT call any tools yourself. Only output a JSON plan that references them.

Each step must be a JSON object with the keys:
  step_id      \u2013 a unique identifier (use sequential integers as strings)
  description  \u2013 plain-English description of what this step does
  action       \u2013 the exact MCP tool name to call, or "analyze"/"summarize" for
                 reasoning-only steps
  parameters   \u2013 a JSON object of parameters the tool expects (omit for
                 analyze/summarize steps)
  status       \u2013 always set to "pending"

Return ONLY the raw JSON array \u2014 no markdown fences, no prose.

Example output:
[
  {"step_id": "1", "description": "List all existing items", "action": "list_items", "parameters": {}, "status": "pending"},
  {"step_id": "2", "description": "Create a new item called Widget", "action": "create_item", "parameters": {"name": "Widget", "description": "A new widget"}, "status": "pending"}
]"""


def _make_mcp_toolset() -> MCPToolset:
    """Create an MCPToolset connected to the standalone MCP server."""
    return MCPToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=f"{settings.mcp_server_url}/mcp",
        ),
    )


def _build_chat_agent() -> LlmAgent:
    """Build the ReAct-style chat agent with MCP tools."""
    return LlmAgent(
        model=settings.gemini_model,
        name="chat_agent",
        instruction=_CHAT_INSTRUCTION,
        tools=[_make_mcp_toolset()],
    )


def _build_planner_agent() -> LlmAgent:
    """Build the planner sub-agent with MCP tool awareness.

    The planner can see MCP tool schemas (names, parameters) so it generates
    plans that reference real tool names.  The instruction forbids the planner
    from actually calling tools \u2014 it only outputs a JSON plan.
    """
    return LlmAgent(
        model=settings.gemini_model,
        name="planner_agent",
        instruction=_PLANNER_INSTRUCTION,
        tools=[_make_mcp_toolset()],
    )


# ---------------------------------------------------------------------------
# ADKAgentManager — the main facade used by API routes
# ---------------------------------------------------------------------------

class ADKAgentManager:
    """Manages Google ADK agent sessions with MongoDB-backed persistent state.

    Uses ``MongodbSessionService`` from the ``adk-mongodb-session`` package
    (analogous to LangGraph's ``MongoDBSaver``) so all conversation history
    and plan state are automatically persisted to MongoDB by the framework.
    """

    APP_NAME = "adk_demo"

    def __init__(self) -> None:
        self._session_service: Optional[MongodbSessionService] = None
        self._chat_runner: Optional[Runner] = None
        self._plan_runner: Optional[Runner] = None

    def initialize(self) -> None:
        """Build session service and runners.

        Must be called once during application startup (inside the lifespan
        context), after the MongoDB connection is established.
        """
        self._session_service = MongodbSessionService(
            db_url=settings.mongodb_url,
            database=settings.mongodb_database,
            collection_prefix="adk",
        )

        self._chat_runner = Runner(
            agent=_build_chat_agent(),
            app_name=self.APP_NAME,
            session_service=self._session_service,
        )

        self._plan_runner = Runner(
            agent=_build_planner_agent(),
            app_name=self.APP_NAME,
            session_service=self._session_service,
        )

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def create_session(self, user_id: str, mode: str = "chat") -> str:
        """Create a new ADK session with initial state persisted to MongoDB."""
        session_id = str(uuid.uuid4())

        await self._session_service.create_session(
            app_name=self.APP_NAME,
            user_id=user_id,
            session_id=session_id,
            state={
                "mode": mode,
                "is_planning_mode": mode == "plan",
                "plan": [],
                "current_step": 0,
                "is_complete": False,
            },
        )

        return session_id

    async def list_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """List sessions for a user using the framework's session service."""
        response = await self._session_service.list_sessions(
            app_name=self.APP_NAME,
            user_id=user_id,
        )
        sessions = []
        for s in response.sessions:
            sessions.append({
                "session_id": s.id,
                "user_id": s.user_id,
                "mode": s.state.get("mode", "chat"),
                "is_planning_mode": s.state.get("is_planning_mode", False),
                "plan": s.state.get("plan", []),
                "current_step": s.state.get("current_step", 0),
                "is_complete": s.state.get("is_complete", False),
                "goal": s.state.get("goal", ""),
                "last_message": s.state.get("last_message", ""),
                "last_update_time": s.last_update_time,
            })
        # Sort by last_update_time descending (most recent first)
        sessions.sort(key=lambda x: x.get("last_update_time") or 0, reverse=True)
        return sessions

    async def get_session_state(self, session_id: str, user_id: str = None) -> Dict[str, Any]:
        """Return the current state of a session from the framework store.

        If user_id is not known, we look it up from the framework's collection.
        """
        if not user_id:
            doc = self._session_service.sessions_collection.find_one({"_id": session_id})
            if not doc:
                raise ValueError(f"Session {session_id} not found")
            user_id = doc["user_id"]

        session = await self._session_service.get_session(
            app_name=self.APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        if not session:
            raise ValueError(f"Session {session_id} not found")

        return {
            "session_id": session.id,
            "user_id": session.user_id,
            "mode": session.state.get("mode", "chat"),
            "goal": session.state.get("goal", ""),
            "is_planning_mode": session.state.get("is_planning_mode", False),
            "plan": session.state.get("plan", []),
            "current_step": session.state.get("current_step", 0),
            "is_complete": session.state.get("is_complete", False),
            "last_update_time": session.last_update_time,
            "event_count": len(session.events),
        }

    async def archive_session(self, session_id: str, user_id: str = None, ttl_days: int = 30) -> Dict[str, Any]:
        """Mark a session as archived in the framework's collection."""
        if not user_id:
            doc = self._session_service.sessions_collection.find_one({"_id": session_id})
            if not doc:
                raise ValueError(f"Session {session_id} not found")
            user_id = doc["user_id"]

        # Update session state to mark as archived
        self._update_session_state(session_id, {"archived": True})

        return {
            "session_id": session_id,
            "status": "archived",
            "ttl_days": ttl_days,
        }

    # ------------------------------------------------------------------
    # Chat mode
    # ------------------------------------------------------------------

    async def chat(self, session_id: str, user_id: str, message: str, auth_token: str = "") -> str:
        """Run a single chat turn and return the agent's text reply."""
        reply_parts = []
        async for chunk in self.chat_stream(session_id, user_id, message, auth_token):
            if chunk.get("type") == "text":
                reply_parts.append(chunk["content"])
        return "".join(reply_parts)

    async def chat_stream(
        self, session_id: str, user_id: str, message: str, auth_token: str = ""
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Run a chat turn and yield streaming events for the frontend."""
        yield {"type": "status", "content": "Connecting to MCP tools..."}

        # Update last_message in session state for sidebar preview
        self._update_session_state(session_id, {
            "last_message": message[:100],
            "mode": "chat",
        })

        # Inject auth token into message so the agent can pass it to tools
        full_message = message
        if auth_token:
            full_message = f"[System context: use auth_token=\"{auth_token}\" for all tool calls]\n\n{message}"

        try:
            async for event in self._chat_runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=Content(
                    role="user",
                    parts=[Part.from_text(text=full_message)],
                ),
            ):
                if not hasattr(event, "content") or not event.content:
                    continue
                if not event.content.parts:
                    continue

                for part in event.content.parts:
                    # Tool call
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        yield {
                            "type": "tool_call",
                            "tool": fc.name,
                            "args": dict(fc.args) if fc.args else {},
                        }
                    # Tool result
                    elif hasattr(part, "function_response") and part.function_response:
                        fr = part.function_response
                        yield {
                            "type": "tool_result",
                            "tool": fr.name,
                            "result": fr.response if fr.response else {},
                        }
                    # Text
                    elif hasattr(part, "text") and part.text:
                        yield {"type": "text", "content": part.text}
        except Exception as exc:
            _log.exception("Chat stream error for session %s", session_id)
            yield {"type": "error", "content": str(exc)}

    # ------------------------------------------------------------------
    # Plan mode
    # ------------------------------------------------------------------

    async def enter_plan_mode(self, session_id: str, goal: str, user_id: str = None) -> Dict[str, Any]:
        """Generate a plan for *goal* and store it in session state."""
        if not user_id:
            doc = self._session_service.sessions_collection.find_one({"_id": session_id})
            if not doc:
                raise ValueError(f"Session {session_id} not found")
            user_id = doc["user_id"]

        # Ask the planner agent to produce the plan
        plan_json = ""
        async for event in self._plan_runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=Content(
                role="user",
                parts=[Part.from_text(text=f"Generate a plan for: {goal}")],
            ),
        ):
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        plan_json += part.text

        # Parse plan (the planner is prompted to return raw JSON)
        plan: List[Dict[str, Any]] = []
        try:
            clean = plan_json.strip()
            if clean.startswith("```"):
                parts = clean.split("```")
                if len(parts) >= 3:
                    inner = parts[1]
                    if inner.startswith("json"):
                        inner = inner[4:]
                    clean = inner.strip()
                else:
                    clean = clean.lstrip("`").lstrip("json").strip()
            plan = json.loads(clean)
            if not isinstance(plan, list):
                raise ValueError("Plan must be a JSON array")
        except (json.JSONDecodeError, ValueError, IndexError) as exc:
            _log.warning(
                "Plan parsing failed for session %s (goal=%r): %s \u2014 using fallback plan",
                session_id, goal, exc,
            )
            plan = [{
                "step_id": "1",
                "description": goal,
                "action": "analyze",
                "status": "pending",
            }]

        # Persist plan to session state via framework's MongoDB collection
        self._update_session_state(session_id, {
            "is_planning_mode": True,
            "mode": "plan",
            "goal": goal,
            "plan": plan,
            "current_step": 0,
            "is_complete": False,
        })

        return {
            "session_id": session_id,
            "mode": "planning",
            "plan": plan,
            "total_steps": len(plan),
        }

    async def execute_step(self, session_id: str, auth_token: str = None) -> Dict[str, Any]:
        """Execute the next pending step in the plan."""
        doc = self._session_service.sessions_collection.find_one({"_id": session_id})
        if not doc:
            raise ValueError(f"Session {session_id} not found")

        user_id = doc["user_id"]
        state = doc.get("state", {})
        plan: List[Dict[str, Any]] = state.get("plan", [])
        current_step: int = state.get("current_step", 0)

        if current_step >= len(plan):
            return {
                "session_id": session_id,
                "status": "completed",
                "message": "All steps have been executed",
                "is_complete": True,
            }

        step = plan[current_step]
        step["status"] = "in_progress"

        # Persist in_progress status BEFORE execution
        plan[current_step] = step
        self._update_session_state(session_id, {"plan": plan})

        # Ask the chat (executor) agent to carry out this step
        step_result_text = ""
        params = step.get("parameters", {})
        step_instruction = (
            f"Execute plan step {step['step_id']}: {step['description']} "
            f"(action: {step['action']})"
        )
        if params:
            step_instruction += f"\nParameters: {json.dumps(params)}"
        if auth_token:
            step_instruction += f'\n[System context: use auth_token="{auth_token}" for all tool calls]'
        async for event in self._chat_runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=Content(
                role="user",
                parts=[Part.from_text(text=step_instruction)],
            ),
        ):
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        step_result_text += part.text

        step["status"] = "completed"
        step["result"] = {"text": step_result_text}

        new_step = current_step + 1
        is_complete = new_step >= len(plan)

        plan[current_step] = step

        # Persist completed status
        updates = {
            "plan": plan,
            "current_step": new_step,
            "is_complete": is_complete,
        }
        if is_complete:
            updates["is_planning_mode"] = False
        self._update_session_state(session_id, updates)

        return {
            "session_id": session_id,
            "step": step,
            "current_step": new_step,
            "total_steps": len(plan),
            "is_complete": is_complete,
        }

    async def execute_all_steps(self, session_id: str, auth_token: str = None) -> Dict[str, Any]:
        """Execute all remaining plan steps sequentially."""
        results = []
        while True:
            result = await self.execute_step(session_id, auth_token=auth_token)
            results.append(result)
            if result.get("is_complete"):
                break
        return {
            "session_id": session_id,
            "execution_results": results,
            "status": "completed",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_session_state(self, session_id: str, updates: Dict[str, Any]) -> None:
        """Update specific keys in the session state document.

        Uses the framework's MongoDB collection directly — this is the minimal
        bridge for plan metadata updates that happen outside of a Runner turn.
        """
        set_fields = {f"state.{k}": v for k, v in updates.items()}
        self._session_service.sessions_collection.update_one(
            {"_id": session_id},
            {"$set": set_fields},
        )


# Global singleton — initialised during app startup
adk_agent = ADKAgentManager()
