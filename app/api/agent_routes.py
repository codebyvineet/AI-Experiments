"""Agent API routes for LangGraph orchestrator.

All agent functionality uses LangGraph framework with:
- Automatic checkpointing (MongoDB via LangGraph)
- Human-in-the-loop approval via interrupt()
- Parallel task execution via Send()
- Session resume, re-plan, and stop features
"""

from typing import Optional, List
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json

from app.auth import get_current_user, require_permission, create_mcp_token
from app.agent.graph import get_orchestrator
from app.models import TokenData

router = APIRouter(prefix="/agent", tags=["agent"])


class GoalRequest(BaseModel):
    """Goal request for LangGraph orchestrator."""
    goal: str
    auto_approve: bool = False


class ApprovalRequest(BaseModel):
    """Approval request model."""
    approved: bool


class ReplanRequest(BaseModel):
    """Re-plan request model."""
    new_goal: str


# ============================================================================
# LangGraph Orchestrator Endpoints (V2 API)
# ============================================================================

@router.post("/v2/sessions")
async def create_session(
    request: GoalRequest,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """
    Create a new LangGraph session and generate plan.
    
    This uses the LangGraph-based orchestrator with:
    - Automatic checkpointing (MongoDB via LangGraph)
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
async def get_session(
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
async def approve_plan(
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
async def stream_session(
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


@router.get("/v2/sessions")
async def list_sessions(
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """
    List all sessions for the current user.
    
    Returns sessions with their status and whether they can be resumed.
    Use this to show pending sessions after page refresh.
    """
    orchestrator = await get_orchestrator()
    
    sessions = await orchestrator.list_user_sessions(current_user.user_id)
    
    return {
        "user_id": current_user.user_id,
        "sessions": sessions,
        "total": len(sessions)
    }


@router.get("/v2/sessions/{session_id}/resume")
async def resume_session(
    session_id: str,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """
    Check if a session can be resumed and get resume info.
    
    Use this on page load to detect pending sessions:
    - If action_needed is "approve", show the plan for approval
    - If action_needed is "stream", reconnect to SSE stream
    - If action_needed is "retry", show retry option for failed session
    
    This is the key endpoint for "resume on refresh" functionality.
    """
    orchestrator = await get_orchestrator()
    
    resume_info = await orchestrator.resume_session(session_id)
    
    if not resume_info.get("resumable"):
        return resume_info
    
    # Verify ownership
    state = await orchestrator.get_session_state(session_id)
    if state and state.get("user_id") != current_user.user_id:
        if "agent:admin" not in (current_user.permissions or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this session"
            )
    
    return resume_info


@router.post("/v2/sessions/{session_id}/replan")
async def replan_session(
    session_id: str,
    request: ReplanRequest,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """
    Interrupt execution and re-plan with new input.
    
    This allows users to:
    - Change the goal mid-execution
    - Add new requirements during planning
    - Correct mistakes in the original request
    
    The session will pause at approval stage with the new plan.
    """
    orchestrator = await get_orchestrator()
    
    # Verify ownership
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
    
    # Generate new MCP token
    mcp_token = await create_mcp_token(current_user)
    
    result = await orchestrator.interrupt_and_replan(
        session_id,
        request.new_goal,
        mcp_token
    )
    
    return result


@router.post("/v2/sessions/{session_id}/stop")
async def stop_session(
    session_id: str,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """
    Stop execution gracefully.
    
    Preserves:
    - All completed results so far
    - Current checkpoint for later resume
    - Session context for re-planning
    
    After stopping, user can:
    - Resume with /retry
    - Re-plan with /replan
    - View partial results
    """
    orchestrator = await get_orchestrator()
    
    # Verify ownership
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
    
    result = await orchestrator.stop_execution(session_id)
    
    return result


@router.post("/v2/sessions/{session_id}/retry")
async def retry_session(
    session_id: str,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """
    Retry a stopped or failed session.
    
    Resumes execution from the last checkpoint,
    continuing from where it left off.
    """
    orchestrator = await get_orchestrator()
    
    # Verify ownership
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
    
    # Generate fresh MCP token
    mcp_token = await create_mcp_token(current_user)
    
    result = await orchestrator.retry_session(session_id, mcp_token)
    
    return result


# ============================================================================
# Backward Compatibility: Redirect Legacy Routes to V2
# ============================================================================

@router.post("/sessions")
async def create_session_legacy(
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """[DEPRECATED] Use POST /agent/v2/sessions instead."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="This endpoint is deprecated. Use POST /agent/v2/sessions with {'goal': '...'}"
    )


@router.get("/sessions/{session_id}")
async def get_session_legacy(
    session_id: str,
    current_user: TokenData = Depends(require_permission("agent:execute"))
):
    """[DEPRECATED] Use GET /agent/v2/sessions/{session_id} instead."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="This endpoint is deprecated. Use GET /agent/v2/sessions/{session_id}"
    )
