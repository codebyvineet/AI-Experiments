"""Main FastAPI application — Google ADK implementation."""

import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.crud import connect_db, disconnect_db
from app.agent import adk_agent
from app.api import auth_router, items_router, agent_router

settings = get_settings()
_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup / shutdown."""
    # --- Startup ---
    print("Starting Google ADK application …")
    await connect_db()
    print("MongoDB connected.")

    # Initialise ADK runners and MongoDB session service
    adk_agent.initialize()
    print("Google ADK agent initialised.")

    yield

    # --- Shutdown ---
    print("Shutting down …")
    await disconnect_db()
    print("MongoDB disconnected.")


app = FastAPI(
    title="MCP Demo — Google ADK Implementation",
    description="""
Containerised Python application demonstrating the **Google ADK** stack:

- **Google ADK** (`LlmAgent` + `SequentialAgent`) — replaces the custom
  LangGraph agent at a fraction of the code
- **Plan mode** — `SequentialAgent` with a planner sub-agent that generates a
  JSON plan and an executor sub-agent that carries out each step using MCP
  tools
- **Chat mode** — `LlmAgent` with MCP tools for ReAct-style tool use
- **MongoDB** — ADK session persistence via `adk-mongodb-session`
- **Redis** — JWT token blacklist
- **FastMCP** — standalone MCP server (separate container) exposes item CRUD
  tools with RBAC
- **JWT / RBAC** — same role-based permissions as the LangGraph implementation
    """,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(items_router)
app.include_router(agent_router)

# Serve frontend build if the dist/ directory exists
_frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_frontend_dist):
    from fastapi.responses import FileResponse

    app.mount("/app/assets", StaticFiles(directory=os.path.join(_frontend_dist, "assets")), name="assets")

    @app.get("/app/{rest_of_path:path}")
    async def serve_spa(rest_of_path: str):
        """Serve the React SPA — all paths under /app/ return index.html."""
        return FileResponse(os.path.join(_frontend_dist, "index.html"))

    _log.info("Frontend static files mounted from %s", _frontend_dist)


@app.get("/")
async def root():
    return {
        "message": "MCP Demo — Google ADK Implementation",
        "version": "1.0.0",
        "framework": "Google ADK",
        "docs": "/docs",
        "endpoints": {
            "auth": "/auth",
            "items": "/items",
            "agent": "/agent",
        },
    }


@app.get("/health")
async def health():
    """Health check with MongoDB and Redis status."""
    from app.crud import get_db
    mongo_ok = False
    redis_ok = False
    try:
        db = get_db()
        await db.command("ping")
        mongo_ok = True
    except Exception:
        pass
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        await r.ping()
        redis_ok = True
        await r.aclose()
    except Exception:
        pass
    return {
        "status": "healthy" if mongo_ok and redis_ok else "degraded",
        "framework": "google-adk",
        "mongodb": "connected" if mongo_ok else "disconnected",
        "redis": "connected" if redis_ok else "disconnected",
    }


@app.get("/mcp/tools")
async def list_mcp_tools():
    """List available MCP tools from the standalone MCP server."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{settings.mcp_server_url}/tools")
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        _log.warning(f"Failed to fetch MCP tools: {e}")
    # Fallback: return known tool definitions
    return {
        "tools": [
            {"name": "list_items", "description": "List all items in the database with pagination", "inputSchema": {"type": "object", "properties": {"skip": {"type": "integer"}, "limit": {"type": "integer"}}}},
            {"name": "read_item", "description": "Read an item from the database by its ID", "inputSchema": {"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]}},
            {"name": "create_item", "description": "Create a new item in the database", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "data": {"type": "object"}}, "required": ["name"]}},
            {"name": "update_item", "description": "Update an existing item in the database", "inputSchema": {"type": "object", "properties": {"item_id": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"}, "data": {"type": "object"}}, "required": ["item_id"]}},
            {"name": "delete_item", "description": "Delete an item from the database", "inputSchema": {"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]}},
            {"name": "search_items", "description": "Search items by text query", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "field": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}},
        ],
        "server_url": settings.mcp_server_url,
    }


@app.get("/mcp/health")
async def mcp_health():
    """Check MCP server health by proxying to its /health endpoint."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.mcp_server_url}/health")
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        _log.warning(f"MCP health check failed: {e}")
    return {"status": "unreachable", "server": "MCP Server"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
