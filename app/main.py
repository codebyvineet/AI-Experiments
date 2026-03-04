"""Main FastAPI application."""

import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import get_settings
from app.config.logging_config import setup_logging, get_logger, LogContext
from app.checkpoints import mongodb_checkpoint, redis_checkpoint
from app.api import auth_router, items_router, agent_router, mcp_router, streaming_router
from app.agent.ai_service import ai_service

# Initialize logging
setup_logging(level="DEBUG", json_format=False)
logger = get_logger("main")

settings = get_settings()


class RequestLoggingMiddleware:
    """Pure ASGI middleware for request logging.
    
    Unlike BaseHTTPMiddleware, this does NOT hold the response body open
    for streaming responses (SSE), so it won't block concurrent requests.
    """
    
    def __init__(self, app: ASGIApp):
        self.app = app
    
    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        
        path = scope.get("path", "")
        method = scope.get("method", "")
        
        log = LogContext(logger, request_id=request_id)
        log.info(f"📥 {method} {path}")
        
        # Wrap send to capture status code and add headers
        response_started = False
        status_code = 0
        
        async def send_wrapper(message):
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message.get("status", 0)
                # Add request ID header
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
                
                duration_ms = int((time.time() - start_time) * 1000)
                emoji = "✅" if status_code < 400 else "❌"
                log.info(f"{emoji} Response {status_code}", duration_ms=duration_ms)
            
            await send(message)
        
        await self.app(scope, receive, send_wrapper)


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
    - MongoDB checkpointing (via LangGraph MongoDBSaver)
    - Redis for auth token blacklist and session cache
    - CRUD operations
    - JWT-based authentication and authorization
    - Real AI-powered agents via Vertex AI
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

# Add request logging middleware (ASGI-native, doesn't block SSE streams)
app.add_middleware(RequestLoggingMiddleware)

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
