"""MCP Server API routes - Proxies to external MCP Server.

These endpoints proxy requests to the external MCP Server container,
which then calls back to the Backend API with proper authorization.
"""

from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from app.auth import get_current_user
from app.mcp.client import list_mcp_tools, call_mcp_tool, mcp_health_check
from app.models import TokenData
from app.config.logging_config import get_logger, LogContext

logger = get_logger("mcp_routes")
router = APIRouter(prefix="/mcp", tags=["mcp"])


class ToolCallRequest(BaseModel):
    """Tool call request model."""
    tool_name: str
    arguments: dict = {}



@router.get("/tools")
async def list_tools(
    current_user: TokenData = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())
):
    """List available MCP tools from external MCP Server."""
    log = LogContext(logger, user_id=current_user.user_id)
    log.info("📥 Request: List MCP tools via external server")
    
    try:
        tools = await list_mcp_tools(token=credentials.credentials)
        log.info(f"📤 Response: {len(tools)} tools available")
        return {"tools": tools}
    except Exception as e:
        log.error(f"❌ Error listing tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tools/call")
async def call_tool(
    request: ToolCallRequest,
    current_user: TokenData = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())
):
    """Call an MCP tool via external MCP Server.
    
    The external MCP Server validates the token and calls the Backend API
    to execute the actual operation.
    """
    log = LogContext(logger, user_id=current_user.user_id)
    log.info(f"📥 Request: Call MCP tool '{request.tool_name}'", data={"arguments": request.arguments})
    
    try:
        result = await call_mcp_tool(
            tool_name=request.tool_name,
            arguments=request.arguments,
            token=credentials.credentials
        )
        log.info(f"📤 Response: Tool '{request.tool_name}' completed")
        return {"tool": request.tool_name, "result": result}
    except PermissionError as e:
        log.error(f"❌ Permission denied: {e}")
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        log.error(f"❌ Error calling tool: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def mcp_health():
    """Check health of external MCP Server."""
    try:
        health = await mcp_health_check()
        return {"status": "healthy", "mcp_server": health}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
