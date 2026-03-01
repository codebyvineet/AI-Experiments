"""MCP Server API routes."""

from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends, Header
from pydantic import BaseModel

from app.auth import get_current_user, require_permission
from app.mcp import mcp_server
from app.models import MCPRequest, MCPResponse, TokenData

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
    current_user: TokenData = Depends(get_current_user)
):
    """List available MCP tools filtered by user permissions."""
    # Generate a token for the current user to pass to MCP server
    from app.auth import create_access_token
    token = create_access_token(
        user_id=current_user.user_id,
        username=current_user.username,
        role=current_user.role
    )
    
    tools = mcp_server.list_tools(token)
    return {"tools": tools}


@router.get("/resources")
async def list_resources(
    current_user: TokenData = Depends(get_current_user)
):
    """List available MCP resources filtered by user permissions."""
    from app.auth import create_access_token
    token = create_access_token(
        user_id=current_user.user_id,
        username=current_user.username,
        role=current_user.role
    )
    
    resources = mcp_server.list_resources(token)
    return {"resources": resources}


@router.post("/tools/call", response_model=MCPResponse)
async def call_tool(
    request: ToolCallRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """Call an MCP tool with RBAC validation."""
    from app.auth import create_access_token
    token = create_access_token(
        user_id=current_user.user_id,
        username=current_user.username,
        role=current_user.role
    )
    
    response = await mcp_server.call_tool(
        token=token,
        tool_name=request.tool_name,
        arguments=request.arguments
    )
    
    return response


@router.post("/resources/read", response_model=MCPResponse)
async def read_resource(
    request: ResourceReadRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """Read an MCP resource with RBAC validation."""
    from app.auth import create_access_token
    token = create_access_token(
        user_id=current_user.user_id,
        username=current_user.username,
        role=current_user.role
    )
    
    response = await mcp_server.read_resource(
        token=token,
        resource_uri=request.resource_uri
    )
    
    return response


@router.post("/request", response_model=MCPResponse)
async def handle_mcp_request(
    request: MCPRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """Handle a raw MCP protocol request."""
    from app.auth import create_access_token
    token = create_access_token(
        user_id=current_user.user_id,
        username=current_user.username,
        role=current_user.role
    )
    
    response = mcp_server.handle_request(request, token)
    return response


@router.get("/capabilities")
async def get_capabilities():
    """Get MCP server capabilities (public endpoint)."""
    return {
        "protocolVersion": "1.0",
        "capabilities": {
            "tools": True,
            "resources": True,
            "prompts": False,
            "sampling": False
        },
        "serverInfo": {
            "name": "MCP Demo Server",
            "version": "1.0.0",
            "description": "MCP Server with RBAC support for AI agents"
        }
    }
