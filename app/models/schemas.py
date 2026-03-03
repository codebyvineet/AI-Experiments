"""Data models for the application."""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from enum import Enum


def utcnow() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class UserRole(str, Enum):
    """User roles for RBAC."""
    ADMIN = "admin"
    USER = "user"
    READ_ONLY = "read_only"


class User(BaseModel):
    """User model."""
    id: Optional[str] = None
    username: str
    email: str
    hashed_password: str
    role: UserRole = UserRole.USER
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class UserCreate(BaseModel):
    """User creation model."""
    username: str
    email: str
    password: str
    role: UserRole = UserRole.USER


class UserResponse(BaseModel):
    """User response model (without password)."""
    id: str
    username: str
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
    permissions: Optional[List[str]] = None


class Token(BaseModel):
    """Token model."""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Token data model."""
    user_id: Optional[str] = None
    username: Optional[str] = None
    role: Optional[UserRole] = None
    permissions: Optional[List[str]] = None


class Item(BaseModel):
    """Generic item model for CRUD operations."""
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    owner_id: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ItemCreate(BaseModel):
    """Item creation model."""
    name: str
    description: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class ItemUpdate(BaseModel):
    """Item update model."""
    name: Optional[str] = None
    description: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


# Note: Agent state is managed by LangGraph (see app/agent/state.py)
# LangGraph checkpointers handle persistence automatically.


class MCPRequest(BaseModel):
    """MCP Server request model."""
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)


class MCPResponse(BaseModel):
    """MCP Server response model."""
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
