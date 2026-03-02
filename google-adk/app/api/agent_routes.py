"""Google ADK agent API routes — plan mode and chat mode."""

from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel

from app.auth import get_current_user, require_permission
from app.agent import adk_agent
from app.models import TokenData

router = APIRouter(prefix="/agent", tags=["agent"])


class ChatRequest(BaseModel):
    message: str


class PlanModeRequest(BaseModel):
    goal: str


class ArchiveRequest(BaseModel):
    ttl_days: int = 30


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

@router.post("/sessions")
async def create_session(
    current_user: TokenData = Depends(require_permission("agent:execute")),
):
    """Create a new ADK agent session."""
    session_id = await adk_agent.create_session(current_user.user_id)
    return {"session_id": session_id, "user_id": current_user.user_id, "status": "created"}


@router.get("/sessions/{session_id}")
async def get_session_state(
    session_id: str,
    current_user: TokenData = Depends(require_permission("agent:execute")),
):
    """Get the current state of an agent session."""
    try:
        state = await adk_agent.get_session_state(session_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    # Enforce ownership (admins can view all)
    if state["user_id"] != current_user.user_id:
        if "agent:admin" not in (current_user.permissions or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this session",
            )

    return state


@router.post("/sessions/{session_id}/archive")
async def archive_session(
    session_id: str,
    request: ArchiveRequest = ArchiveRequest(),
    current_user: TokenData = Depends(require_permission("agent:execute")),
):
    """Archive a session."""
    try:
        return await adk_agent.archive_session(session_id, request.ttl_days)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ---------------------------------------------------------------------------
# Chat mode
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/chat")
async def chat(
    session_id: str,
    request: ChatRequest,
    current_user: TokenData = Depends(require_permission("agent:execute")),
):
    """Send a message to the chat agent and receive a response.

    The Google ADK ``LlmAgent`` uses ReAct-style reasoning and can call
    MCP tools from the standalone MCP server.
    """
    try:
        reply = await adk_agent.chat(
            session_id=session_id,
            user_id=current_user.user_id,
            message=request.message,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return {
        "session_id": session_id,
        "user_message": request.message,
        "agent_reply": reply,
    }


# ---------------------------------------------------------------------------
# Plan mode
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/plan")
async def enter_plan_mode(
    session_id: str,
    request: PlanModeRequest,
    current_user: TokenData = Depends(require_permission("agent:execute")),
):
    """Enter planning mode: the ADK planner agent generates a JSON plan."""
    try:
        return await adk_agent.enter_plan_mode(session_id, request.goal)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/sessions/{session_id}/execute-step")
async def execute_step(
    session_id: str,
    current_user: TokenData = Depends(require_permission("agent:execute")),
):
    """Execute the next pending step in the plan."""
    try:
        return await adk_agent.execute_step(session_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/sessions/{session_id}/execute-all")
async def execute_all_steps(
    session_id: str,
    current_user: TokenData = Depends(require_permission("agent:execute")),
):
    """Execute all remaining steps in the plan."""
    try:
        return await adk_agent.execute_all_steps(session_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
