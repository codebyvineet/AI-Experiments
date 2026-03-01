"""Server-Sent Events (SSE) endpoint for real-time agent streaming."""

import json
import asyncio
import uuid
from typing import Dict, Any, AsyncGenerator, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.auth.authorization import get_current_user, get_current_user_with_token
from app.models import TokenData
from app.agent.multi_agent import multi_agent_orchestrator
from app.mcp.client import mcp_client
from app.config.logging_config import get_logger, LogContext

logger = get_logger("streaming")
router = APIRouter(prefix="/stream", tags=["streaming"])


class CreateSessionRequest(BaseModel):
    goal: str


class UpdatePlanRequest(BaseModel):
    session_id: str
    plan: list


async def event_generator(
    events: AsyncGenerator[Dict[str, Any], None]
) -> AsyncGenerator[str, None]:
    """Convert async generator to SSE format."""
    try:
        async for event in events:
            data = json.dumps(event)
            yield f"data: {data}\n\n"
    except asyncio.CancelledError:
        yield f"data: {json.dumps({'type': 'cancelled'})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"


@router.post("/sessions")
async def create_streaming_session(
    request: CreateSessionRequest,
    auth_data: Tuple[TokenData, str] = Depends(get_current_user_with_token)
):
    """Create a new multi-agent session."""
    current_user, token = auth_data
    request_id = str(uuid.uuid4())[:8]
    log = LogContext(logger, request_id=request_id, user_id=current_user.user_id)
    
    log.info(f"📥 Request: Create streaming session", data={
        "goal": request.goal,
        "permissions": current_user.permissions
    })
    
    user_id = current_user.user_id
    user_permissions = current_user.permissions or []
    
    session = await multi_agent_orchestrator.create_session(
        user_id=user_id, 
        goal=request.goal,
        user_permissions=user_permissions,
        token=token  # Pass token for MCP tool calls during execution
    )
    
    log.info(f"📤 Response: Session created", data={"session_id": session.session_id})
    
    return {
        "session_id": session.session_id,
        "goal": session.goal,
        "status": session.status,
        "created_at": session.created_at.isoformat()
    }


@router.get("/sessions/{session_id}/plan")
async def stream_plan_generation(
    session_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Stream plan generation via Server-Sent Events.
    
    Returns SSE stream with events:
    - {"type": "status", "message": "..."}
    - {"type": "thinking", "agent": "planning", "content": "..."}
    - {"type": "plan_step", "step_number": N, "step": {...}}
    - {"type": "plan_complete", "plan": [...]}
    """
    request_id = str(uuid.uuid4())[:8]
    log = LogContext(logger, request_id=request_id, session_id=session_id, user_id=current_user.user_id)
    
    log.info(f"📥 Request: Stream plan generation (SSE)")
    
    async def generate():
        async for event in multi_agent_orchestrator.generate_plan(session_id):
            log.debug(f"📡 SSE Event: {event.get('type')}", data=event)
            yield event
    
    log.info(f"📤 Response: Starting SSE stream for plan generation")
    
    return StreamingResponse(
        event_generator(generate()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.put("/sessions/{session_id}/plan")
async def update_session_plan(
    session_id: str,
    request: UpdatePlanRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """Update the plan for a session (user modification)."""
    result = await multi_agent_orchestrator.update_plan(session_id, request.plan)
    return result


@router.get("/sessions/{session_id}/execute")
async def stream_plan_execution(
    session_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Stream plan execution via Server-Sent Events.
    
    Returns SSE stream with events:
    - {"type": "status", "status": "executing"}
    - {"type": "step_start", "step_index": N, "step": {...}}
    - {"type": "parallel_start", "task_count": N}
    - {"type": "task_start/task_complete", "task": {...}}
    - {"type": "step_complete", "step_index": N}
    - {"type": "execution_complete", "summary": {...}}
    """
    request_id = str(uuid.uuid4())[:8]
    log = LogContext(logger, request_id=request_id, session_id=session_id, user_id=current_user.user_id)
    
    log.info(f"📥 Request: Stream plan execution (SSE)")
    
    async def generate():
        async for event in multi_agent_orchestrator.execute_plan(session_id):
            log.debug(f"📡 SSE Event: {event.get('type')}", data=event)
            yield event
    
    log.info(f"📤 Response: Starting SSE stream for plan execution")
    
    return StreamingResponse(
        event_generator(generate()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/sessions/{session_id}")
async def get_session_state(
    session_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Get current session state."""
    session = await multi_agent_orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "session_id": session.session_id,
        "goal": session.goal,
        "plan": session.plan,
        "messages": session.messages,
        "status": session.status,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat()
    }


@router.get("/sessions")
async def list_sessions(
    current_user: TokenData = Depends(get_current_user)
):
    """List all sessions for current user."""
    user_id = current_user.user_id
    sessions = multi_agent_orchestrator.get_all_sessions(user_id)
    return {"sessions": sessions}


@router.post("/sessions/{session_id}/message")
async def add_message(
    session_id: str,
    content: str = Query(..., description="Message content"),
    current_user: TokenData = Depends(get_current_user)
):
    """Add a user message to the session."""
    message = await multi_agent_orchestrator.add_message(session_id, "user", content)
    return {"message": message}


@router.get("/mcp/tools")
async def get_mcp_tools(
    current_user: TokenData = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())
):
    """Get available MCP tools for current user via external MCP Server."""
    log = LogContext(logger, user_id=current_user.user_id)
    log.info("📥 Request: Get MCP tools via external server")
    
    try:
        # Get tools from external MCP Server
        tools = await mcp_client.list_tools(token=credentials.credentials)
        
        # Filter by user permissions
        permissions = current_user.permissions or []
        accessible_tools = []
        
        for tool in tools:
            # Check if user has required permission (simplified check)
            tool_name = tool.get("name", "")
            accessible = True  # MCP Server handles permission validation on call
            accessible_tools.append({
                "name": tool_name,
                "description": tool.get("description", ""),
                "inputSchema": tool.get("inputSchema", {}),
                "accessible": accessible
            })
        
        log.info(f"📤 Response: {len(accessible_tools)} tools available")
        return {"tools": accessible_tools}
    except Exception as e:
        log.error(f"❌ Error getting MCP tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mcp/call/{tool_name}")
async def call_mcp_tool(
    tool_name: str,
    args: Dict[str, Any] = {},
    current_user: TokenData = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())
):
    """Call an MCP tool via external MCP Server."""
    log = LogContext(logger, user_id=current_user.user_id)
    log.info(f"📥 Request: Call MCP tool '{tool_name}'", data={"args": args})
    
    try:
        # Call tool via external MCP Server
        result = await mcp_client.call_tool(
            tool_name=tool_name,
            arguments=args,
            token=credentials.credentials
        )
        log.info(f"📤 Response: Tool '{tool_name}' completed")
        return {"tool": tool_name, "result": result}
    except PermissionError as e:
        log.error(f"❌ Permission denied: {e}")
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        log.error(f"❌ Error calling MCP tool: {e}")
        raise HTTPException(status_code=500, detail=str(e))
