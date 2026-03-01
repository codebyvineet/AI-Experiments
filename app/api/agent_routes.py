"""Agent API routes for LangGraph agent with plan mode."""

from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel

from app.auth import get_current_user, require_permission
from app.agent import plan_mode_agent
from app.models import TokenData

router = APIRouter(prefix="/agent", tags=["agent"])


class PlanModeRequest(BaseModel):
    """Plan mode request model."""
    goal: str


class MessageRequest(BaseModel):
    """Message request model."""
    role: str = "user"
    content: str


class ArchiveRequest(BaseModel):
    """Archive request model."""
    ttl_days: int = 30


@router.post("/sessions")
async def create_session(
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """Create a new agent session."""
    session_id = await plan_mode_agent.create_session(current_user.user_id)
    return {
        "session_id": session_id,
        "user_id": current_user.user_id,
        "status": "created"
    }


@router.get("/sessions/{session_id}")
async def get_session_state(
    session_id: str,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """Get the current state of an agent session."""
    try:
        state = await plan_mode_agent.get_session_state(session_id)
        
        # Verify ownership
        if state["user_id"] != current_user.user_id:
            # Admin can view all sessions
            if "agent:admin" not in (current_user.permissions or []):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have access to this session"
                )
        
        return state
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post("/sessions/{session_id}/plan")
async def enter_plan_mode(
    session_id: str,
    request: PlanModeRequest,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """Enter planning mode and generate a plan for a goal."""
    try:
        result = await plan_mode_agent.enter_plan_mode(session_id, request.goal)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post("/sessions/{session_id}/execute-step")
async def execute_step(
    session_id: str,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """Execute the next step in the plan."""
    try:
        result = await plan_mode_agent.execute_step(session_id)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post("/sessions/{session_id}/execute-all")
async def execute_all_steps(
    session_id: str,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """Execute all remaining steps in the plan."""
    try:
        result = await plan_mode_agent.execute_all_steps(session_id)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post("/sessions/{session_id}/messages")
async def add_message(
    session_id: str,
    request: MessageRequest,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """Add a message to the agent session."""
    try:
        result = await plan_mode_agent.add_message(
            session_id,
            request.role,
            request.content
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post("/sessions/{session_id}/archive")
async def archive_session(
    session_id: str,
    request: ArchiveRequest = ArchiveRequest(),
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """Archive a session to cold storage."""
    try:
        result = await plan_mode_agent.archive_session(session_id, request.ttl_days)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
