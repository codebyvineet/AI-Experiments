"""Auth package."""

from app.auth.authorization import (
    authorization_tool,
    AuthorizationTool,
    create_access_token,
    create_mcp_token,
    decode_token,
    get_current_user,
    get_current_user_with_token,
    get_password_hash,
    verify_password,
    require_permission,
    require_role,
    ROLE_PERMISSIONS,
)

__all__ = [
    "authorization_tool",
    "AuthorizationTool",
    "create_access_token",
    "create_mcp_token",
    "decode_token",
    "get_current_user",
    "get_current_user_with_token",
    "get_password_hash",
    "verify_password",
    "require_permission",
    "require_role",
    "ROLE_PERMISSIONS",
]
