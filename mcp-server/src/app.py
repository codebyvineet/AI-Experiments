"""FastAPI wrapper for FastMCP server with JWT authentication.

Endpoints:
1. /health - Health check
2. /tools - List available tools (for UI display)
3. /mcp/* - Native FastMCP streamable-http transport (for MCP clients)
"""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    session_mgr = mcp_http.routes[0].endpoint.session_manager
    async with session_mgr.run():
        yield
    logger.info("👋 Shutting down MCP Server")


app = FastAPI(
    title="AI-Experiments MCP Server",
    version="3.0.0",
    description="FastMCP-based MCP Server with native streamable-http transport",
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


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "server": "AI-Experiments MCP Server",
        "version": "3.0.0",
        "framework": "FastMCP",
        "transport": "streamable-http",
        "protocol": "2024-11-05"
    }


@app.get("/tools")
async def list_tools():
    """List all available MCP tools (for UI display)."""
    tools_list = await mcp.list_tools()
    tools = []
    for tool in tools_list:
        schema = {"type": "object", "properties": {}}
        if tool.parameters:
            props = tool.parameters.get("properties", {})
            # Filter out 'ctx' from properties as it's framework-internal
            props = {k: v for k, v in props.items() if k != "ctx"}
            required = [r for r in tool.parameters.get("required", []) if r != "ctx"]
            schema = {"type": "object", "properties": props}
            if required:
                schema["required"] = required
        tools.append({
            "name": tool.name,
            "description": tool.description or f"Execute {tool.name}",
            "inputSchema": schema
        })
    return {"tools": tools}


# Mount FastMCP's native HTTP transport for MCP protocol
# Clients connect via /mcp for streamable-http
app.mount("/", mcp_http)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("MCP_SERVER_PORT", "8001"))
    logger.info(f"🚀 Starting MCP Server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
