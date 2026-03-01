"""Main FastAPI application."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.checkpoints import mongodb_checkpoint, redis_checkpoint
from app.api import auth_router, items_router, agent_router, mcp_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    print("Starting up...")
    await mongodb_checkpoint.connect()
    await redis_checkpoint.connect()
    print("Connected to MongoDB and Redis")
    
    yield
    
    # Shutdown
    print("Shutting down...")
    await mongodb_checkpoint.disconnect()
    await redis_checkpoint.disconnect()
    print("Disconnected from MongoDB and Redis")


app = FastAPI(
    title="MCP Demo Application",
    description="""
    A containerized Python application demonstrating:
    - MCP Server with RBAC support
    - LangGraph agent with plan mode
    - Hot state checkpoints (MongoDB)
    - Cold state checkpoints (Redis)
    - CRUD operations
    - JWT-based authentication and authorization
    """,
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(items_router)
app.include_router(agent_router)
app.include_router(mcp_router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "MCP Demo Application",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "auth": "/auth",
            "items": "/items",
            "agent": "/agent",
            "mcp": "/mcp"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "mongodb": "connected" if mongodb_checkpoint.client else "disconnected",
        "redis": "connected" if redis_checkpoint.client else "disconnected"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug
    )
