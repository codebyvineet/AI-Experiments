"""Main FastAPI application — Google ADK implementation."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.crud import connect_db, disconnect_db
from app.agent import adk_agent
from app.api import auth_router, items_router, agent_router

settings = get_settings()


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
        async with httpx.AsyncClient(timeout=5) as client:
            # Use SSE to get tools list from MCP server
            resp = await client.get(f"{settings.mcp_server_url}/sse")
            # Fallback: return the known tools
    except Exception:
        pass
    # Return known tool definitions (static for the current MCP server)
    return {
        "tools": [
            {"name": "list_items", "description": "List all items in the system", "parameters": {"limit": "int (default 50)", "auth_token": "string"}},
            {"name": "read_item", "description": "Read a single item by ID", "parameters": {"item_id": "string", "auth_token": "string"}},
            {"name": "create_item", "description": "Create a new item", "parameters": {"name": "string", "description": "string", "data": "JSON string", "auth_token": "string"}},
            {"name": "update_item", "description": "Update an existing item", "parameters": {"item_id": "string", "name": "string?", "description": "string?", "data": "JSON string?", "auth_token": "string"}},
            {"name": "delete_item", "description": "Delete an item by ID", "parameters": {"item_id": "string", "auth_token": "string"}},
        ],
        "server_url": settings.mcp_server_url,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
