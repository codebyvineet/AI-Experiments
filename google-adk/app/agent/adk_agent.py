"""Google ADK agent implementation — replaces the custom LangGraph agent.

Architecture
------------
Two operating modes share the same ADK ``Runner`` and MongoDB session store:

Chat mode  — a single ``LlmAgent`` with MCP tools executes ReAct-style
             tool calls in one turn.

Plan mode  — a two-phase workflow:
               1. Planner ``LlmAgent``  – generates a JSON plan of steps.
               2. Executor ``LlmAgent`` – carries out each step one at a time
                  using MCP tools, called via the chat runner.

Session State Strategy
----------------------
ADK session state is updated via ``append_event`` with ``state_delta``
(the recommended event-driven pattern).  Plan metadata is *also* mirrored
to the ``agent_sessions`` MongoDB collection so the REST API can query it
without re-running the agent.

Session persistence uses ``adk-mongodb-session`` (``MongodbSessionService``),
which stores the full conversation history and state in MongoDB.

The Redis token blacklist used by ``authorization.py`` is unchanged.

MCP tools are fetched from the standalone MCP server at startup via
``MCPToolset`` so the server stays completely independent.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.adk.agents import LlmAgent
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.tools.mcp_tool import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import SseConnectionParams
from google.genai.types import Content, Part

from app.config import get_settings
from app.crud import get_db

settings = get_settings()
_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session service (MongoDB-backed via adk-mongodb-session)
# ---------------------------------------------------------------------------

def _build_session_service():
    """Lazily import and instantiate the MongoDB session service."""
    from adk_mongodb_session.mongodb.sessions import MongodbSessionService  # type: ignore

    return MongodbSessionService(
        db_url=settings.mongodb_url,
        database=settings.mongodb_database,
        collection_prefix="adk",
    )


# ---------------------------------------------------------------------------
# ADK agents
# ---------------------------------------------------------------------------

_CHAT_INSTRUCTION = """You are a helpful AI assistant with access to tools for
managing items (create, read, update, delete). Use the available tools to
fulfil user requests accurately. Always confirm actions you have taken."""

_PLANNER_INSTRUCTION = """You are a planning agent. Given a user goal, produce
a JSON execution plan as a list of steps.

Each step must be a JSON object with the keys:
  step_id      – a unique identifier (use sequential integers as strings)
  description  – plain-English description of what this step does
  action       – one of: create_item | read_item | update_item | delete_item |
                          list_items | analyze | summarize
  status       – always set to "pending"

Return ONLY the raw JSON array — no markdown fences, no prose.

Example output:
[
  {"step_id": "1", "description": "List all existing items", "action": "list_items", "status": "pending"},
  {"step_id": "2", "description": "Create a new item called Widget", "action": "create_item", "status": "pending"}
]"""


def _make_mcp_toolset() -> MCPToolset:
    """Create an MCPToolset connected to the standalone MCP server."""
    return MCPToolset(
        connection_params=SseConnectionParams(
            url=f"{settings.mcp_server_url}/sse",
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
    """Build the planner sub-agent (no tools — pure reasoning)."""
    return LlmAgent(
        model=settings.gemini_model,
        name="planner_agent",
        instruction=_PLANNER_INSTRUCTION,
    )


# ---------------------------------------------------------------------------
# ADKAgentManager — the main facade used by API routes
# ---------------------------------------------------------------------------

class ADKAgentManager:
    """Manages Google ADK agent sessions with MongoDB-backed state.

    Replaces the custom ``PlanModeAgent`` from the LangGraph implementation
    using a fraction of the boilerplate.
    """

    APP_NAME = "adk_demo"

    def __init__(self) -> None:
        self._session_service = None
        self._chat_runner: Optional[Runner] = None
        self._plan_runner: Optional[Runner] = None

    def initialize(self) -> None:
        """Build session service and runners.

        Must be called once during application startup (inside the lifespan
        context), after the MongoDB connection is established.
        """
        self._session_service = _build_session_service()

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

    async def create_session(self, user_id: str) -> str:
        """Create a new ADK session and persist metadata to MongoDB."""
        session_id = str(uuid.uuid4())

        await self._session_service.create_session(
            app_name=self.APP_NAME,
            user_id=user_id,
            session_id=session_id,
            state={
                "is_planning_mode": False,
                "plan": [],
                "current_step": 0,
                "is_complete": False,
            },
        )

        await self._save_session_meta(session_id, user_id)
        return session_id

    async def get_session_state(self, session_id: str) -> Dict[str, Any]:
        """Return the current state of a session."""
        meta = await self._load_session_meta(session_id)
        if not meta:
            raise ValueError(f"Session {session_id} not found")

        return {
            "session_id": session_id,
            "user_id": meta["user_id"],
            "is_planning_mode": meta.get("is_planning_mode", False),
            "plan": meta.get("plan", []),
            "current_step": meta.get("current_step", 0),
            "is_complete": meta.get("is_complete", False),
            "created_at": meta.get("created_at"),
            "updated_at": meta.get("updated_at"),
        }

    async def archive_session(self, session_id: str, ttl_days: int = 30) -> Dict[str, Any]:
        """Mark a session as archived."""
        meta = await self._load_session_meta(session_id)
        if not meta:
            raise ValueError(f"Session {session_id} not found")

        db = get_db()
        await db.agent_sessions.update_one(
            {"session_id": session_id},
            {"$set": {
                "archived": True,
                "ttl_days": ttl_days,
                "updated_at": datetime.now(timezone.utc),
            }},
        )

        return {
            "session_id": session_id,
            "status": "archived",
            "ttl_days": ttl_days,
        }

    # ------------------------------------------------------------------
    # Chat mode
    # ------------------------------------------------------------------

    async def chat(self, session_id: str, user_id: str, message: str) -> str:
        """Run a single chat turn and return the agent's text reply."""
        events = []
        async for event in self._chat_runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=Content(
                role="user",
                parts=[Part.from_text(message)],
            ),
        ):
            events.append(event)

        # Extract the final model text response
        for event in reversed(events):
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        return part.text
        return ""

    # ------------------------------------------------------------------
    # Plan mode
    # ------------------------------------------------------------------

    async def enter_plan_mode(self, session_id: str, goal: str) -> Dict[str, Any]:
        """Generate a plan for *goal* and store it in session state."""
        meta = await self._load_session_meta(session_id)
        if not meta:
            raise ValueError(f"Session {session_id} not found")

        user_id = meta["user_id"]

        # Ask the planner agent to produce the plan
        plan_json = ""
        async for event in self._plan_runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=Content(
                role="user",
                parts=[Part.from_text(f"Generate a plan for: {goal}")],
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
            # Strip markdown code fences if the model wrapped the JSON
            if clean.startswith("```"):
                parts = clean.split("```")
                if len(parts) >= 3:
                    # Content is between the first pair of fences
                    inner = parts[1]
                    if inner.startswith("json"):
                        inner = inner[4:]
                    clean = inner.strip()
                else:
                    # Malformed fences — try removing just the opening fence
                    clean = clean.lstrip("`").lstrip("json").strip()
            plan = json.loads(clean)
            if not isinstance(plan, list):
                raise ValueError("Plan must be a JSON array")
        except (json.JSONDecodeError, ValueError, IndexError) as exc:
            _log.warning(
                "Plan parsing failed for session %s (goal=%r): %s — using fallback plan",
                session_id, goal, exc,
            )
            plan = [{
                "step_id": "1",
                "description": goal,
                "action": "analyze",
                "status": "pending",
            }]

        # Update ADK session state via append_event (event-driven pattern)
        state_delta = {
            "is_planning_mode": True,
            "plan": plan,
            "current_step": 0,
            "is_complete": False,
        }
        await self._update_adk_state(session_id, user_id, state_delta)

        # Mirror to our own metadata collection for fast API queries
        await self._update_session_meta(session_id, state_delta)

        return {
            "session_id": session_id,
            "mode": "planning",
            "plan": plan,
            "total_steps": len(plan),
        }

    async def execute_step(self, session_id: str) -> Dict[str, Any]:
        """Execute the next pending step in the plan."""
        meta = await self._load_session_meta(session_id)
        if not meta:
            raise ValueError(f"Session {session_id} not found")

        user_id = meta["user_id"]
        plan: List[Dict[str, Any]] = meta.get("plan", [])
        current_step: int = meta.get("current_step", 0)

        if current_step >= len(plan):
            return {
                "session_id": session_id,
                "status": "completed",
                "message": "All steps have been executed",
                "is_complete": True,
            }

        step = plan[current_step]
        step["status"] = "in_progress"

        # Ask the chat (executor) agent to carry out this step
        step_result_text = ""
        async for event in self._chat_runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=Content(
                role="user",
                parts=[Part.from_text(
                    f"Execute plan step {step['step_id']}: {step['description']} "
                    f"(action: {step['action']})"
                )],
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
        state_delta: Dict[str, Any] = {
            "plan": plan,
            "current_step": new_step,
            "is_complete": is_complete,
        }
        if is_complete:
            state_delta["is_planning_mode"] = False

        # Persist updates
        await self._update_adk_state(session_id, user_id, state_delta)
        await self._update_session_meta(session_id, state_delta)

        return {
            "session_id": session_id,
            "step": step,
            "current_step": new_step,
            "total_steps": len(plan),
            "is_complete": is_complete,
        }

    async def execute_all_steps(self, session_id: str) -> Dict[str, Any]:
        """Execute all remaining plan steps sequentially."""
        results = []
        while True:
            result = await self.execute_step(session_id)
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

    async def _update_adk_state(
        self,
        session_id: str,
        user_id: str,
        state_delta: Dict[str, Any],
    ) -> None:
        """Push a state update into the ADK session via append_event."""
        from google.adk.events import EventActions  # type: ignore

        adk_session = await self._session_service.get_session(
            app_name=self.APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        if adk_session is None:
            return

        event = Event(
            author="system",
            actions=EventActions(state_delta=state_delta),
        )
        await self._session_service.append_event(adk_session, event)

    async def _save_session_meta(self, session_id: str, user_id: str) -> None:
        """Persist lightweight session metadata to the agent_sessions collection."""
        db = get_db()
        now = datetime.now(timezone.utc)
        await db.agent_sessions.update_one(
            {"session_id": session_id},
            {
                "$setOnInsert": {
                    "session_id": session_id,
                    "user_id": user_id,
                    "is_planning_mode": False,
                    "plan": [],
                    "current_step": 0,
                    "is_complete": False,
                    "archived": False,
                    "created_at": now,
                },
                "$set": {"updated_at": now},
            },
            upsert=True,
        )

    async def _update_session_meta(
        self,
        session_id: str,
        updates: Dict[str, Any],
    ) -> None:
        """Update session metadata in the agent_sessions collection."""
        db = get_db()
        updates["updated_at"] = datetime.now(timezone.utc)
        await db.agent_sessions.update_one(
            {"session_id": session_id},
            {"$set": updates},
        )

    async def _load_session_meta(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load session metadata from the agent_sessions collection."""
        db = get_db()
        doc = await db.agent_sessions.find_one({"session_id": session_id})
        if doc:
            doc.pop("_id", None)
        return doc


# Global singleton — initialised during app startup
adk_agent = ADKAgentManager()
