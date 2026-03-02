"""Agent API routes for LangGraph agent with plan mode."""

from typing import Optional, List
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json

from app.auth import get_current_user, require_permission, create_mcp_token
from app.agent import plan_mode_agent
from app.agent.graph import get_orchestrator
from app.models import TokenData

router = APIRouter(prefix="/agent", tags=["agent"])


class PlanModeRequest(BaseModel):
    """Plan mode request model."""
    goal: str


class GoalRequest(BaseModel):
    """Goal request for LangGraph orchestrator."""
    goal: str
    auto_approve: bool = False


class ApprovalRequest(BaseModel):
    """Approval request model."""
    approved: bool


class MessageRequest(BaseModel):
    """Message request model."""
    role: str = "user"
    content: str


class ArchiveRequest(BaseModel):
    """Archive request model."""
    ttl_days: int = 30


# ============================================================================
# NEW: LangGraph Orchestrator Endpoints
# ============================================================================

@router.post("/v2/sessions")
async def create_session_v2(
    request: GoalRequest,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """
    Create a new LangGraph session and generate plan.
    
    This uses the new LangGraph-based orchestrator with:
    - Automatic checkpointing to MongoDB
    - Human-in-the-loop approval via interrupt()
    - Parallel task execution via Send()
    
    The session will pause at approval stage.
    Use /v2/sessions/{id}/approve to continue.
    """
    orchestrator = await get_orchestrator()
    
    # Generate MCP token for tool authorization
    mcp_token = await create_mcp_token(current_user)
    
    session_id = await orchestrator.create_session(
        user_id=current_user.user_id,
        goal=request.goal,
        token=mcp_token
    )
    
    # Get the generated plan
    state = await orchestrator.get_session_state(session_id)
    
    return {
        "session_id": session_id,
        "user_id": current_user.user_id,
        "status": state.get("status", "awaiting_approval") if state else "created",
        "plan": state.get("plan", []) if state else [],
        "message": "Plan generated. Use /v2/sessions/{id}/approve to execute."
    }


@router.get("/v2/sessions/{session_id}")
async def get_session_v2(
    session_id: str,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """Get the current state of a LangGraph session."""
    orchestrator = await get_orchestrator()
    
    state = await orchestrator.get_session_state(session_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    # Verify ownership
    if state.get("user_id") != current_user.user_id:
        if "agent:admin" not in (current_user.permissions or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this session"
            )
    
    return state


@router.post("/v2/sessions/{session_id}/approve")
async def approve_plan_v2(
    session_id: str,
    request: ApprovalRequest,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """
    Approve or reject the plan and continue execution.
    
    If approved, the plan will be executed automatically.
    If rejected, the session will be marked as failed.
    """
    orchestrator = await get_orchestrator()
    
    # Verify session exists and user has access
    state = await orchestrator.get_session_state(session_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    if state.get("user_id") != current_user.user_id:
        if "agent:admin" not in (current_user.permissions or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this session"
            )
    
    result = await orchestrator.approve_plan(session_id, request.approved)
    
    return {
        "session_id": session_id,
        "approved": request.approved,
        "status": result.get("status", "unknown"),
        "summary": result.get("summary")
    }


@router.get("/v2/sessions/{session_id}/stream")
async def stream_session_v2(
    session_id: str,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """
    Stream session events via Server-Sent Events (SSE).
    
    Connect to this endpoint to receive real-time updates:
    - task_complete: When a task finishes
    - step_complete: When a step finishes
    - execution_complete: When all done
    - error: On failures
    """
    orchestrator = await get_orchestrator()
    
    # Verify access
    state = await orchestrator.get_session_state(session_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    if state.get("user_id") != current_user.user_id:
        if "agent:admin" not in (current_user.permissions or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this session"
            )
    
    async def generate():
        async for event in orchestrator.stream_session(session_id):
            yield f"data: {json.dumps(event)}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )


# ============================================================================
# LEGACY: Original Plan Mode Agent Endpoints
# ============================================================================


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
