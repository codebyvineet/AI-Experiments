"""Data models for the Google ADK application."""

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


class PlanStep(BaseModel):
    """A single step in an agent plan."""
    step_id: str
    description: str
    action: str
    status: str = "pending"  # pending | in_progress | completed | failed
    result: Optional[Dict[str, Any]] = None


class AgentSessionInfo(BaseModel):
    """Agent session info stored alongside ADK sessions."""
    session_id: str
    user_id: str
    is_planning_mode: bool = False
    plan: List[Dict[str, Any]] = Field(default_factory=list)
    current_step: int = 0
    is_complete: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
