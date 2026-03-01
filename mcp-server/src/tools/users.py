"""User profile tools for MCP Server."""
import logging
from typing import Any, Dict
from .registry import register_tool
from ..backend_client import backend_client

logger = logging.getLogger(__name__)


# Tool: get_user_profile
async def handle_get_user_profile(arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Get current user profile."""
    logger.info("[get_user_profile] Fetching user profile")
    result = await backend_client.get_user_profile(token)
    return result


register_tool(
    name="get_user_profile",
    description="Get the profile information of the currently authenticated user.",
    input_schema={
        "type": "object",
        "properties": {},
        "required": []
    },
    handler=handle_get_user_profile,
    category="users",
    tags=["user", "profile", "read"],
    permissions=["users:read"],
    endpoint="/auth/me",
    http_method="GET"
)


# Tool: update_user_profile
async def handle_update_user_profile(arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Update current user profile."""
    profile_data = {k: v for k, v in arguments.items() if k not in ["token"]}
    
    if not profile_data:
        raise ValueError("No profile data provided to update")
    
    logger.info(f"[update_user_profile] Updating profile with: {list(profile_data.keys())}")
    result = await backend_client.update_user_profile(token, profile_data)
    return result


register_tool(
    name="update_user_profile",
    description="Update the profile of the currently authenticated user.",
    input_schema={
        "type": "object",
        "properties": {
            "display_name": {
                "type": "string",
                "description": "Display name for the user"
            },
            "email": {
                "type": "string",
                "description": "Email address"
            },
            "preferences": {
                "type": "object",
                "description": "User preferences (JSON object)"
            }
        },
        "required": []
    },
    handler=handle_update_user_profile,
    category="users",
    tags=["user", "profile", "write", "update"],
    permissions=["users:write"],
    endpoint="/auth/profile",
    http_method="PUT"
)
