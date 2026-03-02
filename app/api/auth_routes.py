"""Authentication API routes."""

from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel

from app.auth import (
    authorization_tool,
    verify_password,
    get_current_user,
    ROLE_PERMISSIONS,
)
from app.crud import user_crud
from app.models import UserCreate, UserResponse, Token, TokenData, UserRole

router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    """Login request model."""
    username: str
    password: str


class TokenRequest(BaseModel):
    """Token generation request model."""
    user_id: str
    username: str
    role: UserRole
    expires_minutes: Optional[int] = None


class TokenValidateRequest(BaseModel):
    """Token validation request model."""
    token: str


@router.post("/register", response_model=UserResponse)
async def register_user(user_data: UserCreate):
    """Register a new user."""
    try:
        user = await user_crud.create_user(user_data)
        return UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
            updated_at=user.updated_at
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/login", response_model=Token)
async def login(request: LoginRequest):
    """Login and get access token."""
    user = await user_crud.get_user_by_username(request.username)
    
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )
    
    token_data = await authorization_tool.generate_user_token(
        user_id=user.id,
        username=user.username,
        role=user.role
    )
    
    return Token(
        access_token=token_data["access_token"],
        token_type=token_data["token_type"]
    )


@router.post("/token/generate")
async def generate_token(request: TokenRequest):
    """
    Internal API to generate token for MCP server RBAC.
    This endpoint can be used to generate tokens programmatically.
    """
    token_data = await authorization_tool.generate_user_token(
        user_id=request.user_id,
        username=request.username,
        role=request.role,
        expires_minutes=request.expires_minutes
    )
    
    return token_data


@router.post("/token/validate")
async def validate_token(request: TokenValidateRequest):
    """Validate a token and return its data."""
    try:
        token_data = authorization_tool.validate_token(request.token)
        return {
            "valid": True,
            "user_id": token_data.user_id,
            "username": token_data.username,
            "role": token_data.role.value if token_data.role else None,
            "permissions": token_data.permissions
        }
    except HTTPException as e:
        return {
            "valid": False,
            "error": e.detail
        }


@router.post("/token/revoke")
async def revoke_token(
    request: TokenValidateRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """Revoke a token (requires authentication)."""
    await authorization_tool.revoke_token(request.token)
    return {"status": "revoked"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: TokenData = Depends(get_current_user)
):
    """Get current authenticated user information."""
    user = await user_crud.get_user(current_user.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at
    )


@router.get("/permissions/{role}")
async def get_role_permissions(role: UserRole):
    """Get all permissions for a specific role."""
    permissions = authorization_tool.get_permissions_for_role(role)
    return {
        "role": role.value,
        "permissions": permissions
    }


@router.get("/roles")
async def list_roles():
    """List all available roles and their permissions."""
    return {
        role.value: ROLE_PERMISSIONS[role]
        for role in UserRole
    }
