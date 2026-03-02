"""FastAPI wrapper for FastMCP server with JWT authentication.

This provides HTTP endpoints that:
1. Validate JWT tokens from Backend API
2. Set the token for tool execution
3. Proxy requests to FastMCP
"""
import os
import json
import logging
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Import the FastMCP server and token setter
from . import server as mcp_server

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv("BACKEND_URL", "http://app:8000")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("🚀 Starting MCP Server (FastMCP-based)")
    logger.info(f"📡 Backend URL: {BACKEND_URL}")
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
    # Get tools from FastMCP server
    tools = []
    for name, tool in mcp_server.mcp._tools.items():
        tools.append({
            "name": name,
            "description": tool.description or f"Execute {name}",
            "inputSchema": tool.parameters.model_json_schema() if tool.parameters else {}
        })
    return {"tools": tools}


# ============================================================================
# MCP PROTOCOL ENDPOINTS (JSON-RPC Compatible)
# ============================================================================

class JSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    method: str
    params: Optional[Dict[str, Any]] = None


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
            tools = []
            for name, tool in mcp_server.mcp._tools.items():
                tools.append({
                    "name": name,
                    "description": tool.description or f"Execute {name}",
                    "inputSchema": tool.parameters.model_json_schema() if tool.parameters else {}
                })
            result = {"tools": tools}
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
            
            # Set token for the tool execution
            mcp_server._current_token = token
            
            try:
                # Get and call the tool
                tool = mcp_server.mcp._tools.get(tool_name)
                if not tool:
                    raise ValueError(f"Unknown tool: {tool_name}")
                
                # Execute the tool
                tool_result = await tool.fn(**arguments)
                
                result = {
                    "content": [
                        {"type": "text", "text": json.dumps(tool_result)}
                    ]
                }
            finally:
                mcp_server._current_token = None
                
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
        logger.error(f"[MCP] Internal error: {e}", exc_info=True)
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": str(e)}
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
    
    # Set token and call tool
    mcp_server._current_token = token
    
    try:
        tool = mcp_server.mcp._tools.get(tool_name)
        if not tool:
            raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")
        
        result = await tool.fn(**body)
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        mcp_server._current_token = None


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("MCP_SERVER_PORT", "8001"))
    logger.info(f"🚀 Starting MCP Server on port {port}")
    
    uvicorn.run(app, host="0.0.0.0", port=port)
