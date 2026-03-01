"""Main FastAPI application."""

import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.config.logging_config import setup_logging, get_logger, LogContext
from app.checkpoints import mongodb_checkpoint, redis_checkpoint
from app.api import auth_router, items_router, agent_router, mcp_router, streaming_router
from app.agent.ai_service import ai_service

# Initialize logging
setup_logging(level="DEBUG", json_format=False)
logger = get_logger("main")

settings = get_settings()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all incoming requests and responses."""
    
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        
        # Extract user info if available
        user_info = "anonymous"
        if "authorization" in request.headers:
            user_info = "authenticated"
        
        log = LogContext(logger, request_id=request_id)
        
        # Log request
        log.info(f"📥 {request.method} {request.url.path}", data={
            "query_params": dict(request.query_params),
            "user": user_info,
            "client": request.client.host if request.client else "unknown"
        })
        
        # Process request
        response = await call_next(request)
        
        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Log response
        status_emoji = "✅" if response.status_code < 400 else "❌"
        log.info(f"{status_emoji} Response {response.status_code}", data={
            "status_code": response.status_code
        }, duration_ms=duration_ms)
        
        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    log = LogContext(logger)
    
    # Startup
    log.info("🚀 Starting MCP Demo Application...")
    
    log.info("📦 Connecting to MongoDB...")
    await mongodb_checkpoint.connect()
    log.info("✅ MongoDB connected")
    
    log.info("📦 Connecting to Redis...")
    await redis_checkpoint.connect()
    log.info("✅ Redis connected")
    
    log.info("🤖 Initializing AI service (Vertex AI)...")
    ai_initialized = await ai_service.initialize()
    if ai_initialized:
        log.info("✅ AI service initialized")
    else:
        log.warning("⚠️ AI service initialization failed - will use fallback mode")
    
    log.info("🎉 Application startup complete!")
    
    yield
    
    # Shutdown
    log.info("🛑 Shutting down...")
    await mongodb_checkpoint.disconnect()
    await redis_checkpoint.disconnect()
    log.info("👋 Application shutdown complete")


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
    - Real AI-powered agents via Vertex AI
    """,
    version="1.0.0",
    lifespan=lifespan
)

# Add request logging middleware
app.add_middleware(RequestLoggingMiddleware)

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
app.include_router(streaming_router)


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
