"""API package."""

from fastapi import APIRouter

from app.api.auth_routes import router as auth_router
from app.api.items_routes import router as items_router
from app.api.agent_routes import router as agent_router

__all__ = ["auth_router", "items_router", "agent_router"]
