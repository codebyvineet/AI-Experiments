"""MCP Server - Main FastAPI Application.

This is a Model Context Protocol (MCP) compliant server that provides tools
for the AI agent to interact with the Backend API.

Transport Layer: HTTP with SSE
- GET /sse - Server-sent events for server→client streaming
- POST /message - JSON-RPC endpoint for client→server requests

Data Layer: JSON-RPC 2.0
- initialize - Lifecycle handshake
- tools/list - List available tools
- tools/call - Execute a tool
- resources/list - List available resources
- resources/read - Read a resource
"""
import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from .config import settings
from .protocol.jsonrpc import (
    parse_request, create_response, create_error_response, JSONRPCError
)
from .protocol.lifecycle import handle_initialize, handle_initialized, handle_shutdown, handle_ping
from .protocol.tools import handle_tools_list, handle_tools_call
from .protocol.resources import handle_resources_list, handle_resources_read

# Import tools to register them
from .tools import items, search, batch, reports, users

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Session storage for SSE connections
class MCPSession:
    """Represents an MCP client session."""
    
    def __init__(self, session_id: str, token: Optional[str] = None):
        self.session_id = session_id
        self.token = token
        self.initialized = False
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.created_at = asyncio.get_event_loop().time()
    
    async def send_message(self, message: Dict[str, Any]):
        """Queue a message to be sent to the client via SSE."""
        await self.message_queue.put(message)
    
    async def get_messages(self):
        """Generator that yields messages for SSE streaming."""
        while True:
            try:
                message = await asyncio.wait_for(self.message_queue.get(), timeout=30.0)
                yield message
            except asyncio.TimeoutError:
                # Send keepalive
                yield {"type": "keepalive"}


sessions: Dict[str, MCPSession] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info(f"[MCP Server] Starting on port {settings.MCP_SERVER_PORT}")
    logger.info(f"[MCP Server] Backend URL: {settings.BACKEND_URL}")
    logger.info(f"[MCP Server] Protocol version: {settings.PROTOCOL_VERSION}")
    yield
    logger.info("[MCP Server] Shutting down")
    sessions.clear()


app = FastAPI(
    title=settings.SERVER_NAME,
    version=settings.SERVER_VERSION,
    description="MCP Server for AI-Experiments",
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


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "server": settings.SERVER_NAME,
        "version": settings.SERVER_VERSION,
        "protocol": settings.PROTOCOL_VERSION
    }


@app.get("/sse")
async def sse_endpoint(
    request: Request,
    authorization: Optional[str] = Header(None)
):
    """SSE endpoint for server→client streaming.
    
    This implements the MCP transport layer for server-sent events.
    Clients connect here to receive streaming responses and then
    use the provided endpoint URI to send requests.
    """
    session_id = str(uuid.uuid4())
    token = extract_token(authorization)
    
    logger.info(f"[MCP SSE] New connection: session_id={session_id}")
    
    session = MCPSession(session_id, token)
    sessions[session_id] = session
    
    async def event_stream():
        try:
            # Send endpoint event with POST URI
            endpoint_event = {
                "uri": f"/message?session_id={session_id}"
            }
            yield {
                "event": "endpoint",
                "data": json.dumps(endpoint_event)
            }
            logger.info(f"[MCP SSE] Sent endpoint event for session {session_id}")
            
            # Stream messages from the session queue
            async for message in session.get_messages():
                if message.get("type") == "keepalive":
                    yield {"event": "keepalive", "data": ""}
                else:
                    yield {
                        "event": "message",
                        "data": json.dumps(message)
                    }
        except asyncio.CancelledError:
            logger.info(f"[MCP SSE] Connection closed: session_id={session_id}")
        finally:
            # Cleanup session
            if session_id in sessions:
                del sessions[session_id]
                logger.info(f"[MCP SSE] Session cleaned up: {session_id}")
    
    return EventSourceResponse(event_stream())


@app.post("/message")
async def message_endpoint(
    request: Request,
    session_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None)
):
    """JSON-RPC message endpoint for client→server requests.
    
    This implements the MCP transport layer for receiving JSON-RPC requests.
    """
    token = extract_token(authorization)
    
    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        logger.error(f"[MCP Message] Invalid JSON: {e}")
        return JSONResponse(
            content=create_error_response(None, JSONRPCError.PARSE_ERROR, "Invalid JSON"),
            status_code=400
        )
    
    logger.info(f"[MCP Message] Received: method={body.get('method')}, id={body.get('id')}")
    logger.debug(f"[MCP Message] Full request: {json.dumps(body)}")
    
    # Parse JSON-RPC request
    try:
        rpc_request = parse_request(body)
    except ValueError as e:
        logger.error(f"[MCP Message] Invalid request: {e}")
        return JSONResponse(
            content=create_error_response(body.get("id"), JSONRPCError.INVALID_REQUEST, str(e)),
            status_code=400
        )
    
    # Get token from request params if not in header (for flexibility)
    if not token and rpc_request.params:
        meta = rpc_request.params.get("_meta", {})
        token = meta.get("token")
    
    # Route to appropriate handler
    try:
        result = await route_request(rpc_request.method, rpc_request.params or {}, token)
        
        # If it's a notification (no id), don't send response
        if rpc_request.id is None:
            return JSONResponse(content={})
        
        response = create_response(rpc_request.id, result)
        logger.info(f"[MCP Message] Response for {rpc_request.method}: success")
        logger.debug(f"[MCP Message] Full response: {json.dumps(response)}")
        
        return JSONResponse(content=response)
        
    except PermissionError as e:
        logger.error(f"[MCP Message] Permission error: {e}")
        return JSONResponse(
            content=create_error_response(rpc_request.id, JSONRPCError.UNAUTHORIZED, str(e)),
            status_code=401
        )
    except ValueError as e:
        logger.error(f"[MCP Message] Value error: {e}")
        return JSONResponse(
            content=create_error_response(rpc_request.id, JSONRPCError.INVALID_PARAMS, str(e)),
            status_code=400
        )
    except Exception as e:
        logger.error(f"[MCP Message] Internal error: {e}", exc_info=True)
        return JSONResponse(
            content=create_error_response(rpc_request.id, JSONRPCError.INTERNAL_ERROR, str(e)),
            status_code=500
        )


async def route_request(method: str, params: Dict[str, Any], token: Optional[str]) -> Any:
    """Route a JSON-RPC request to the appropriate handler."""
    logger.info(f"[MCP Router] Routing method: {method}")
    
    # Lifecycle methods
    if method == "initialize":
        return await handle_initialize(params)
    elif method == "initialized":
        await handle_initialized()
        return {}
    elif method == "shutdown":
        return await handle_shutdown()
    elif method == "ping":
        return await handle_ping()
    
    # Tool methods
    elif method == "tools/list":
        return await handle_tools_list(params)
    elif method == "tools/call":
        if not token:
            raise PermissionError("Authorization token required for tools/call")
        return await handle_tools_call(params, token)
    
    # Resource methods
    elif method == "resources/list":
        return await handle_resources_list(params)
    elif method == "resources/read":
        if not token:
            raise PermissionError("Authorization token required for resources/read")
        return await handle_resources_read(params, token)
    
    else:
        logger.warning(f"[MCP Router] Unknown method: {method}")
        raise ValueError(f"Unknown method: {method}")


# Simple endpoint for direct tool calls (non-SSE mode)
@app.post("/tools/{tool_name}")
async def direct_tool_call(
    tool_name: str,
    request: Request,
    authorization: Optional[str] = Header(None)
):
    """Direct tool call endpoint (convenience method, bypasses full MCP protocol)."""
    token = extract_token(authorization)
    
    if not token:
        raise HTTPException(status_code=401, detail="Authorization token required")
    
    try:
        body = await request.json()
    except:
        body = {}
    
    logger.info(f"[Direct Tool] Calling: {tool_name}")
    
    try:
        result = await handle_tools_call({"name": tool_name, "arguments": body}, token)
        return result
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tools")
async def list_tools_direct():
    """List all available tools (convenience endpoint)."""
    result = await handle_tools_list()
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.MCP_SERVER_HOST, port=settings.MCP_SERVER_PORT)
