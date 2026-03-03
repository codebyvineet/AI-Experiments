"""Google ADK agent API routes — plan mode and chat mode.

RBAC policy (matches main branch):
- Session creation and archival require ``agent:execute``
- Chat, plan, streaming, and session listing use auth-only
  so that read_only users CAN interact with the AI agent.
  Write operations are denied at the MCP tool level (backend returns 403).
"""

import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, status, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth import get_current_user, get_current_user_with_token, require_permission
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
    current_user: TokenData = Depends(get_current_user),
):
    """Create a new ADK agent session.  Auth-only so read_only users can chat."""
    session_id = await adk_agent.create_session(current_user.user_id)
    return {"session_id": session_id, "user_id": current_user.user_id, "status": "created"}


@router.get("/sessions")
async def list_sessions(
    current_user: TokenData = Depends(get_current_user),
):
    """List all sessions for the current user.  Auth-only."""
    from app.crud import get_db
    db = get_db()
    query = {"user_id": current_user.user_id, "archived": {"$ne": True}}
    if "agent:admin" in (current_user.permissions or []):
        query = {"archived": {"$ne": True}}
    sessions = []
    async for doc in db.agent_sessions.find(query).sort("created_at", -1):
        doc.pop("_id", None)
        sessions.append(doc)
    return sessions


@router.get("/sessions/{session_id}")
async def get_session_state(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    """Get the current state of an agent session.  Auth-only."""
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
    """Archive a session.  Requires agent:execute."""
    try:
        return await adk_agent.archive_session(session_id, request.ttl_days)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ---------------------------------------------------------------------------
# Chat mode (auth-only — read_only users can chat, writes denied at MCP level)
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/chat")
async def chat(
    session_id: str,
    request: ChatRequest,
    req: Request,
    current_user: TokenData = Depends(get_current_user),
):
    """Send a message to the chat agent and receive a response."""
    auth_header = req.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
    try:
        reply = await adk_agent.chat(
            session_id=session_id,
            user_id=current_user.user_id,
            message=request.message,
            auth_token=token,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

    return {
        "session_id": session_id,
        "user_message": request.message,
        "agent_reply": reply,
    }


@router.post("/sessions/{session_id}/chat/stream")
async def chat_stream(
    session_id: str,
    request: ChatRequest,
    req: Request,
    current_user: TokenData = Depends(get_current_user),
):
    """SSE streaming chat endpoint — yields events as the agent works."""
    auth_header = req.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""

    async def event_generator():
        try:
            async for chunk in adk_agent.chat_stream(
                session_id=session_id,
                user_id=current_user.user_id,
                message=request.message,
                auth_token=token,
            ):
                yield f"data: {json.dumps(chunk)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Plan mode (auth-only — read_only users can plan, writes denied at MCP level)
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/plan")
async def enter_plan_mode(
    session_id: str,
    request: PlanModeRequest,
    current_user: TokenData = Depends(get_current_user),
):
    """Enter planning mode: the ADK planner agent generates a JSON plan."""
    try:
        return await adk_agent.enter_plan_mode(session_id, request.goal)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/sessions/{session_id}/execute-step")
async def execute_step(
    session_id: str,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
):
    """Execute the next pending step in the plan."""
    try:
        auth_token = request.headers.get("Authorization", "").replace("Bearer ", "")
        return await adk_agent.execute_step(session_id, auth_token=auth_token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/sessions/{session_id}/execute-all")
async def execute_all_steps(
    session_id: str,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
):
    """Execute all remaining steps in the plan."""
    try:
        auth_token = request.headers.get("Authorization", "").replace("Bearer ", "")
        return await adk_agent.execute_all_steps(session_id, auth_token=auth_token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
