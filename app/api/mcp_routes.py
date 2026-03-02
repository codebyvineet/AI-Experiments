"""MCP Server API routes - Proxies to external MCP Server.

These endpoints proxy requests to the external MCP Server container,
which then calls back to the Backend API with proper authorization.
"""

from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from app.auth import get_current_user
from app.mcp.client import mcp_client
from app.models import TokenData
from app.config.logging_config import get_logger, LogContext

logger = get_logger("mcp_routes")
router = APIRouter(prefix="/mcp", tags=["mcp"])


class ToolCallRequest(BaseModel):
    """Tool call request model."""
    tool_name: str
    arguments: dict = {}


class ResourceReadRequest(BaseModel):
    """Resource read request model."""
    resource_uri: str


@router.get("/tools")
async def list_tools(
    current_user: TokenData = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())
):
    """List available MCP tools from external MCP Server."""
    log = LogContext(logger, user_id=current_user.user_id)
    log.info("📥 Request: List MCP tools via external server")
    
    try:
        tools = await mcp_client.list_tools(token=credentials.credentials)
        log.info(f"📤 Response: {len(tools)} tools available")
        return {"tools": tools}
    except Exception as e:
        log.error(f"❌ Error listing tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/resources")
async def list_resources(
    current_user: TokenData = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())
):
    """List available MCP resources from external MCP Server."""
    log = LogContext(logger, user_id=current_user.user_id)
    log.info("📥 Request: List MCP resources via external server")
    
    try:
        resources = await mcp_client.list_resources(token=credentials.credentials)
        log.info(f"📤 Response: {len(resources)} resources available")
        return {"resources": resources}
    except Exception as e:
        log.error(f"❌ Error listing resources: {e}")
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
        result = await mcp_client.call_tool(
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


@router.post("/resources/read")
async def read_resource(
    request: ResourceReadRequest,
    current_user: TokenData = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())
):
    """Read an MCP resource via external MCP Server."""
    log = LogContext(logger, user_id=current_user.user_id)
    log.info(f"📥 Request: Read MCP resource '{request.resource_uri}'")
    
    try:
        result = await mcp_client.read_resource(
            uri=request.resource_uri,
            token=credentials.credentials
        )
        log.info(f"📤 Response: Resource '{request.resource_uri}' read")
        return {"resource": request.resource_uri, "result": result}
    except PermissionError as e:
        log.error(f"❌ Permission denied: {e}")
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        log.error(f"❌ Error reading resource: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/capabilities")
async def get_capabilities():
    """Get MCP server capabilities via external MCP Server."""
    try:
        # Initialize connection to get server info
        info = await mcp_client.initialize()
        return {
            "protocolVersion": info.get("protocolVersion", "2024-11-05"),
            "capabilities": info.get("capabilities", {}),
            "serverInfo": info.get("serverInfo", {})
        }
    except Exception as e:
        # Return basic capabilities if server not reachable
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": False, "listChanged": True}
            },
            "serverInfo": {
                "name": "MCP Server",
                "version": "1.0.0",
                "description": "External MCP Server (separate container)"
            },
            "status": "external_server",
            "note": "Connect via MCP_SERVER_URL environment variable"
        }


@router.get("/health")
async def mcp_health():
    """Check health of external MCP Server."""
    try:
        health = await mcp_client.health_check()
        return {"status": "healthy", "mcp_server": health}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
