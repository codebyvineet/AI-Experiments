"""FastAPI wrapper for FastMCP server with JWT authentication.

This provides HTTP endpoints that work with the MCP client:
1. /message - JSON-RPC endpoint (for tool calls)
2. /tools - List available tools
3. /health - Health check

The actual tools are defined in server.py using FastMCP decorators.
"""
import os
import json
import logging
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Import the FastMCP server with tools
from .server import mcp, BACKEND_URL

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Create FastMCP's HTTP app for streamable-http transport
mcp_http = mcp.http_app()


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    """Application lifespan handler — includes FastMCP session manager init."""
    logger.info("🚀 Starting MCP Server (FastMCP-based)")
    logger.info(f"📡 Backend URL: {BACKEND_URL}")
    # Initialize the StreamableHTTPSessionManager task group
    session_mgr = mcp_http.routes[0].endpoint.session_manager
    async with session_mgr.run():
        yield
    logger.info("👋 Shutting down MCP Server")


app = FastAPI(
    title="AI-Experiments MCP Server",
    version="2.0.0",
    description="FastMCP-based MCP Server with JWT authentication",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def extract_token(authorization: Optional[str]) -> Optional[str]:
    """Extract Bearer token from Authorization header."""
    if not authorization:
        return None
    if authorization.startswith("Bearer "):
        return authorization[7:]
    return authorization


async def validate_token(token: str) -> bool:
    """Validate JWT token with Backend API."""
    try:
        async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=10.0) as client:
            response = await client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {token}"}
            )
            return response.status_code == 200
    except Exception as e:
        logger.error(f"Token validation failed: {e}")
        return False


# ============================================================================
# HEALTH & INFO ENDPOINTS
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "server": "AI-Experiments MCP Server",
        "version": "2.0.0",
        "framework": "FastMCP",
        "protocol": "2024-11-05"
    }


@app.get("/tools")
async def list_tools():
    """List all available MCP tools."""
    tools_list = await mcp.list_tools()
    tools = []
    for tool in tools_list:
        # Get schema from parameters dict, filtering out auth_token
        schema = {"type": "object", "properties": {}}
        if tool.parameters:
            props = tool.parameters.get("properties", {})
            # Remove 'auth_token' from properties as it's injected by wrapper
            props = {k: v for k, v in props.items() if k != "auth_token"}
            required = [r for r in tool.parameters.get("required", []) if r != "auth_token"]
            schema = {"type": "object", "properties": props}
            if required:
                schema["required"] = required
        
        tools.append({
            "name": tool.name,
            "description": tool.description or f"Execute {tool.name}",
            "inputSchema": schema
        })
    return {"tools": tools}


# ============================================================================
# MCP PROTOCOL ENDPOINT (JSON-RPC Compatible)
# ============================================================================

class JSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    method: str
    params: Optional[Dict[str, Any]] = None


# Mock context for tool execution (since we're not using FastMCP's native transport)
class MockContext:
    """Mock context to pass authorization token to tools."""
    def __init__(self, token: str):
        self._token = token
        self.request = MockRequest(token)
    
    @property
    def request_context(self):
        return type('obj', (object,), {'meta': {'token': self._token}})()


class MockRequest:
    """Mock request with headers."""
    def __init__(self, token: str):
        self.headers = {"Authorization": f"Bearer {token}"}


@app.post("/message")
async def handle_message(
    request: Request,
    authorization: Optional[str] = Header(None)
):
    """Handle JSON-RPC messages (MCP protocol)."""
    token = extract_token(authorization)
    
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            content={"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}},
            status_code=400
        )
    
    method = body.get("method", "")
    params = body.get("params", {})
    request_id = body.get("id")
    
    logger.info(f"[MCP] Method: {method}, ID: {request_id}")
    
    try:
        # Handle lifecycle methods
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": True},
                    "resources": {"subscribe": False, "listChanged": True}
                },
                "serverInfo": {
                    "name": "AI-Experiments MCP Server",
                    "version": "2.0.0"
                }
            }
        elif method == "initialized":
            result = {}
        elif method == "ping":
            result = {"pong": True}
        elif method == "tools/list":
            # Get tools from FastMCP server (same as /tools endpoint)
            tools_response = await list_tools()
            result = tools_response
        elif method == "tools/call":
            if not token:
                raise PermissionError("Authorization token required for tools/call")
            
            # Validate token
            if not await validate_token(token):
                raise PermissionError("Invalid or expired token")
            
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            if not tool_name:
                raise ValueError("Missing tool name")
            
            # Get tool to check it exists
            tool = await mcp.get_tool(tool_name)
            if not tool:
                raise ValueError(f"Unknown tool: {tool_name}")
            
            # Add token to arguments for authorization
            arguments_with_token = {**arguments, "auth_token": token}
            
            # Call tool via FastMCP
            tool_result = await mcp.call_tool(tool_name, arguments_with_token)
            
            # Extract content from result
            content = []
            if tool_result.content:
                for item in tool_result.content:
                    if hasattr(item, 'text'):
                        content.append({"type": "text", "text": item.text})
                    else:
                        content.append({"type": "text", "text": str(item)})
            
            result = {"content": content}
                
        elif method == "resources/list":
            result = {"resources": []}
        elif method == "resources/read":
            raise ValueError("Resource not found")
        else:
            raise ValueError(f"Unknown method: {method}")
        
        # Return response
        if request_id is None:
            return JSONResponse(content={})
        
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result
        })
        
    except PermissionError as e:
        logger.error(f"[MCP] Permission error: {e}")
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32001, "message": str(e)}
            },
            status_code=401
        )
    except ValueError as e:
        logger.error(f"[MCP] Value error: {e}")
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": str(e)}
            },
            status_code=400
        )
    except Exception as e:
        error_msg = str(e)
        # ToolError wrapping PermissionError → return 403, not 500
        if "Permission denied" in error_msg or "Forbidden" in error_msg or "Unauthorized" in error_msg:
            logger.warning(f"[MCP] Permission error: {error_msg}")
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32001, "message": error_msg}
                },
                status_code=403
            )
        logger.error(f"[MCP] Internal error: {e}", exc_info=True)
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": error_msg}
            },
            status_code=500
        )


# ============================================================================
# DIRECT TOOL CALL ENDPOINTS (Convenience)
# ============================================================================

@app.post("/tools/{tool_name}")
async def direct_tool_call(
    tool_name: str,
    request: Request,
    authorization: Optional[str] = Header(None)
):
    """Direct tool call endpoint (bypasses JSON-RPC)."""
    token = extract_token(authorization)
    
    if not token:
        raise HTTPException(status_code=401, detail="Authorization required")
    
    if not await validate_token(token):
        raise HTTPException(status_code=401, detail="Invalid token")
    
    try:
        body = await request.json()
    except:
        body = {}
    
    logger.info(f"[Direct] Calling tool: {tool_name}")
    
    tool = mcp._tools.get(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")
    
    try:
        # Create mock context with token
        ctx = MockContext(token)
        result = await tool.fn(ctx=ctx, **body)
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# NATIVE MCP ENDPOINT (for langchain-mcp-adapters)
# ============================================================================

# Mount FastMCP's native HTTP transport
# http_app() provides route at /mcp for streamable-http protocol
# langchain-mcp-adapters MultiServerMCPClient connects to this
app.mount("/", mcp_http)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("MCP_SERVER_PORT", "8001"))
    logger.info(f"🚀 Starting MCP Server on port {port}")
    
    uvicorn.run(app, host="0.0.0.0", port=port)
