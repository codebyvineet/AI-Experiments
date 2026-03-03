"""Server-Sent Events (SSE) endpoint for real-time agent streaming.

All streaming uses the LangGraph orchestrator for consistent behavior.
"""

import json
import asyncio
import uuid
from typing import Dict, Any, AsyncGenerator, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.auth.authorization import get_current_user, get_current_user_with_token, create_mcp_token
from app.models import TokenData
from app.agent.graph import get_orchestrator
from app.agent.react_agent import chat_stream
from app.mcp.client import list_mcp_tools, call_mcp_tool as invoke_mcp_tool
from app.config.logging_config import get_logger, LogContext

logger = get_logger("streaming")
router = APIRouter(prefix="/stream", tags=["streaming"])


class CreateSessionRequest(BaseModel):
    goal: str


class ChatRequest(BaseModel):
    message: str


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


@router.post("/chat")
async def stream_chat(
    request: ChatRequest,
    auth_data: Tuple[TokenData, str] = Depends(get_current_user_with_token)
):
    """
    ReAct Chat Mode — AI directly calls MCP tools and responds.

    Uses LangGraph's prebuilt create_react_agent with ChatVertexAI + MCP tools.
    No planning step, no approval — the AI autonomously reasons, calls tools,
    and produces a final answer in a single streaming response.

    Streams SSE events:
      - thinking: AI is connecting / reasoning
      - tool_call: AI decided to call an MCP tool
      - tool_result: Tool execution result
      - response: Final AI answer
      - error: On failure
    """
    current_user, raw_token = auth_data
    request_id = str(uuid.uuid4())[:8]
    log = LogContext(logger, request_id=request_id, user_id=current_user.user_id)

    log.info("📥 Request: Chat (ReAct mode)", data={"message": request.message[:100]})

    # Generate MCP token for tool authorization
    mcp_token = await create_mcp_token(current_user)

    async def generate():
        async for event in chat_stream(
            message=request.message,
            token=mcp_token,
            user_id=current_user.user_id,
        ):
            yield event

    log.info("📤 Response: Starting SSE stream for chat")

    return StreamingResponse(
        event_generator(generate()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions")
async def create_streaming_session(
    request: CreateSessionRequest,
    auth_data: Tuple[TokenData, str] = Depends(get_current_user_with_token)
):
    """
    Create a new LangGraph session - returns immediately with session ID.
    
    Client should then connect to GET /sessions/{id}/plan SSE to stream planning progress.
    This avoids blocking the POST request during AI plan generation (~20-30s).
    """
    current_user, token = auth_data
    request_id = str(uuid.uuid4())[:8]
    log = LogContext(logger, request_id=request_id, user_id=current_user.user_id)
    
    log.info(f"📥 Request: Create streaming session", data={
        "goal": request.goal,
        "permissions": current_user.permissions
    })
    
    orchestrator = await get_orchestrator()
    
    # Generate MCP token for tool calls
    mcp_token = await create_mcp_token(current_user)
    
    # Just create session ID and initial state - don't start graph yet
    session_id, initial_state, config = orchestrator.create_session_id(
        user_id=current_user.user_id,
        goal=request.goal,
        token=mcp_token
    )
    
    # Store session info for later retrieval (before streaming starts)
    # We'll store in a simple in-memory dict keyed by session_id
    _pending_sessions[session_id] = {
        "initial_state": initial_state,
        "config": config,
        "user_id": current_user.user_id,
        "goal": request.goal
    }
    
    log.info(f"📤 Response: Session created (pending planning)", data={"session_id": session_id})
    
    return {
        "session_id": session_id,
        "goal": request.goal,
        "status": "pending",
        "plan": []
    }


# In-memory store for pending sessions awaiting streaming
_pending_sessions: Dict[str, Dict[str, Any]] = {}


@router.get("/sessions/{session_id}/plan")
async def stream_plan_generation(
    session_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Stream plan generation via Server-Sent Events.
    
    If session is pending, starts graph execution and streams progress.
    If session already has a plan, streams the existing plan.
    """
    request_id = str(uuid.uuid4())[:8]
    log = LogContext(logger, request_id=request_id, session_id=session_id, user_id=current_user.user_id)
    
    log.info(f"📥 Request: Stream plan (SSE)")
    
    orchestrator = await get_orchestrator()
    
    # Check if this is a pending session that needs execution
    pending = _pending_sessions.get(session_id)
    
    if pending:
        # Start graph execution with streaming
        log.info(f"🚀 Starting graph execution for pending session")
        
        async def stream_new_plan():
            _pending_sessions.pop(session_id, None)  # Safe to remove once streaming begins
            async for event in orchestrator.stream_graph(
                session_id,
                pending["initial_state"],
                pending["config"]
            ):
                yield event
        
        log.info(f"📤 Response: Starting SSE stream for new plan generation")
        return StreamingResponse(
            event_generator(stream_new_plan()),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    
    # Session already exists - return existing state
    state = await orchestrator.get_session_state(session_id)
    
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    
    async def generate_existing():
        # Send plan status
        yield {"type": "status", "status": state.get("status", "unknown")}
        
        # Send plan steps
        for i, step in enumerate(state.get("plan", [])):
            yield {
                "type": "plan_step",
                "step_number": i + 1,
                "step": step
            }
        
        # Send completion
        yield {
            "type": "plan_complete",
            "plan": state.get("plan", []),
            "total_steps": len(state.get("plan", []))
        }
    
    log.info(f"📤 Response: Starting SSE stream for existing plan")
    
    return StreamingResponse(
        event_generator(generate_existing()),
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
    log = LogContext(logger, session_id=session_id, user_id=current_user.user_id)
    log.info("📥 Request: Update plan")
    
    orchestrator = await get_orchestrator()
    
    # Verify ownership
    state = await orchestrator.get_session_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    if state.get("user_id") != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Update plan in LangGraph state via aupdate_state
    config = {"configurable": {"thread_id": session_id}}
    try:
        await orchestrator._graph.aupdate_state(
            config,
            {"plan": request.plan},
            as_node="planner"  # Update as if planner produced this plan
        )
    except Exception as e:
        log.error(f"❌ Failed to update plan: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update plan: {str(e)}")
    
    log.info("📤 Response: Plan updated")
    return {
        "session_id": session_id,
        "message": "Plan updated successfully",
        "plan": request.plan
    }


@router.get("/sessions/{session_id}/execute")
async def stream_plan_execution(
    session_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Stream plan execution via Server-Sent Events.
    
    Resumes past the approval interrupt and executes the plan.
    Uses LangGraph orchestrator with automatic checkpointing.
    """
    request_id = str(uuid.uuid4())[:8]
    log = LogContext(logger, request_id=request_id, session_id=session_id, user_id=current_user.user_id)
    
    log.info(f"📥 Request: Stream plan execution (SSE)")
    
    orchestrator = await get_orchestrator()
    
    # Verify access
    state = await orchestrator.get_session_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if state.get("user_id") != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    async def generate():
        # Pass approve=True to resume past the approval interrupt
        async for event in orchestrator.stream_session(session_id, approve=True):
            log.debug(f"📡 SSE Event: {event.get('type')}", data=event)
            yield event
    
    log.info(f"📤 Response: Starting SSE stream for execution")
    
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
    """Get current session state from LangGraph."""
    orchestrator = await get_orchestrator()
    state = await orchestrator.get_session_state(session_id)
    
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return state


@router.get("/sessions")
async def list_sessions(
    current_user: TokenData = Depends(get_current_user)
):
    """List all sessions for current user."""
    orchestrator = await get_orchestrator()
    sessions = await orchestrator.list_user_sessions(current_user.user_id)
    return {"sessions": sessions}


@router.post("/sessions/{session_id}/stop")
async def stop_session(
    session_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Stop a running session gracefully.
    
    Saves checkpoint to MongoDB so session can be resumed later.
    Works for both planning and executing states.
    """
    request_id = str(uuid.uuid4())[:8]
    log = LogContext(logger, request_id=request_id, session_id=session_id, user_id=current_user.user_id)
    
    log.info("📥 Request: Stop session")
    
    orchestrator = await get_orchestrator()
    
    # Verify ownership
    state = await orchestrator.get_session_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if state.get("user_id") != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Stop execution (checkpoints are saved automatically)
    result = await orchestrator.stop_execution(session_id)
    
    log.info("📤 Response: Session stopped", data=result)
    
    return result


@router.post("/sessions/{session_id}/resume")
async def resume_session(
    session_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Resume a stopped session from its checkpoint.
    
    Returns session state and streams execution if needed.
    """
    request_id = str(uuid.uuid4())[:8]
    log = LogContext(logger, request_id=request_id, session_id=session_id, user_id=current_user.user_id)
    
    log.info("📥 Request: Resume session")
    
    orchestrator = await get_orchestrator()
    
    # Get resume info
    resume_info = await orchestrator.resume_session(session_id)
    
    if not resume_info.get("resumable"):
        raise HTTPException(
            status_code=400, 
            detail=resume_info.get("reason", "Session cannot be resumed")
        )
    
    # Verify ownership
    if resume_info.get("user_id") and resume_info.get("user_id") != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    log.info("📤 Response: Session resume info", data=resume_info)
    
    return resume_info


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    permanent: bool = False,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Delete/cancel a session.
    
    Args:
        permanent: If True, permanently deletes the session from the database.
                  If False (default), just marks it as cancelled.
    """
    request_id = str(uuid.uuid4())[:8]
    log = LogContext(logger, request_id=request_id, session_id=session_id, user_id=current_user.user_id)
    
    log.info(f"📥 Request: Delete session (permanent={permanent})")
    
    orchestrator = await get_orchestrator()
    
    # Verify ownership
    state = await orchestrator.get_session_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if state.get("user_id") != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if permanent:
        # Permanently delete from MongoDB
        from app.checkpoints import get_mongodb
        db = await get_mongodb()
        
        # Delete from checkpoints collection
        result1 = await db.checkpoints.delete_many({"thread_id": session_id})
        # Delete from checkpoint_writes collection
        result2 = await db.checkpoint_writes.delete_many({"thread_id": session_id})
        
        log.info(f"📤 Response: Session permanently deleted (checkpoints: {result1.deleted_count}, writes: {result2.deleted_count})")
        
        return {
            "message": "Session permanently deleted",
            "session_id": session_id,
            "deleted_checkpoints": result1.deleted_count,
            "deleted_writes": result2.deleted_count
        }
    else:
        # Mark as cancelled in the state
        # We use aupdate_state with the "summary" node which leads to END
        # This marks the session as complete/cancelled
        config = {"configurable": {"thread_id": session_id}}
        try:
            await orchestrator._graph.aupdate_state(
                config,
                {"status": "cancelled", "final_result": "Session cancelled by user"},
                as_node="summary"
            )
        except Exception as e:
            # If update fails (e.g., graph structure doesn't allow it),
            # just log it - the session is effectively abandoned
            log.warning(f"Could not update state (session may be orphaned): {e}")
        
        log.info("📤 Response: Session cancelled")
        
        return {"message": "Session cancelled", "session_id": session_id}


class MessageRequest(BaseModel):
    content: str


@router.post("/sessions/{session_id}/message")
async def add_message(
    session_id: str,
    request: MessageRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Add a user message to a session.
    
    Behavior depends on current session state:
    - awaiting_approval: Message modifies the goal, triggers re-plan
    - executing: Stops execution and re-plans with new context
    - completed/stopped: Starts new planning cycle with message as new goal
    """
    request_id = str(uuid.uuid4())[:8]
    log = LogContext(logger, request_id=request_id, session_id=session_id, user_id=current_user.user_id)
    
    log.info("📥 Request: Add message", data={"content": request.content[:100]})
    
    orchestrator = await get_orchestrator()
    
    # Verify ownership
    state = await orchestrator.get_session_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if state.get("user_id") != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    mcp_token = await create_mcp_token(current_user)
    
    # Use replan feature with the new message
    result = await orchestrator.interrupt_and_replan(
        session_id,
        request.content,
        mcp_token
    )
    
    log.info("📤 Response: Message processed", data={"status": result.get("status")})
    
    return {"message": "Message processed", "result": result}


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
        tools = await list_mcp_tools(token=credentials.credentials)
        
        accessible_tools = []
        for tool in tools:
            accessible_tools.append({
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "inputSchema": tool.get("inputSchema", {}),
                "accessible": True  # MCP Server handles permission validation on call
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
        result = await invoke_mcp_tool(
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
