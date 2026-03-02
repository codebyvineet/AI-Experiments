"""FastMCP Server with token-based authentication.

This is a clean FastMCP implementation that uses:
- auth_token parameter for authorization (passed from JSON-RPC wrapper)
- @mcp.tool decorators for automatic schema generation
- Native FastMCP framework

The auth_token is injected by the JSON-RPC wrapper (app.py) when calling tools.
"""
import os
import logging
from typing import Optional, Dict, Any

import httpx
from fastmcp import FastMCP
from pydantic import Field

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://app:8000")
MCP_SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "8001"))


async def backend_request(
    method: str,
    path: str,
    token: str,
    json_data: Optional[Dict] = None,
    params: Optional[Dict] = None
) -> Dict[str, Any]:
    """Make an authorized request to the Backend API."""
    logger.info(f"[Backend] {method} {path}")
    
    async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=30.0) as client:
        headers = {"Authorization": f"Bearer {token}"}
        
        response = await client.request(
            method=method,
            url=path,
            headers=headers,
            json=json_data,
            params=params
        )
        
        logger.info(f"[Backend] Response: {response.status_code}")
        
        if response.status_code == 401:
            raise PermissionError("Unauthorized - invalid or expired token")
        if response.status_code == 403:
            raise PermissionError("Forbidden - insufficient permissions")
        if response.status_code == 404:
            return {"error": "Not found", "status_code": 404}
        
        response.raise_for_status()
        return response.json()


# Create FastMCP server
mcp = FastMCP(
    name="AI-Experiments MCP Server"
)


# ============================================================================
# ITEM CRUD TOOLS
# ============================================================================

@mcp.tool
async def create_item(
    name: str = Field(description="The name of the item (required)"),
    description: str = Field(default="", description="A description of the item"),
    data: dict = Field(default_factory=dict, description="Additional JSON data"),
    auth_token: str = Field(default="", description="Authorization token (injected by wrapper)")
) -> dict:
    """Create a new item in the database."""
    logger.info(f"[create_item] Creating: {name}")
    return await backend_request(
        "POST", "/items/",
        token=auth_token,
        json_data={"name": name, "description": description, "data": data}
    )


@mcp.tool
async def read_item(
    item_id: str = Field(description="The unique ID of the item to read"),
    auth_token: str = Field(default="", description="Authorization token (injected by wrapper)")
) -> dict:
    """Read an item from the database by its ID."""
    logger.info(f"[read_item] Reading: {item_id}")
    return await backend_request("GET", f"/items/{item_id}", token=auth_token)


@mcp.tool
async def update_item(
    item_id: str = Field(description="The unique ID of the item to update"),
    auth_token: str = Field(default="", description="Authorization token (injected by wrapper)"),
    name: Optional[str] = Field(default=None, description="New name for the item"),
    description: Optional[str] = Field(default=None, description="New description"),
    data: Optional[dict] = Field(default=None, description="New JSON data")
) -> dict:
    """Update an existing item in the database."""
    logger.info(f"[update_item] Updating: {item_id}")
    
    update_data = {}
    if name is not None:
        update_data["name"] = name
    if description is not None:
        update_data["description"] = description
    if data is not None:
        update_data["data"] = data
    
    return await backend_request("PUT", f"/items/{item_id}", token=auth_token, json_data=update_data)


@mcp.tool
async def delete_item(
    item_id: str = Field(description="The unique ID of the item to delete"),
    auth_token: str = Field(default="", description="Authorization token (injected by wrapper)")
) -> dict:
    """Delete an item from the database. This action is permanent."""
    logger.info(f"[delete_item] Deleting: {item_id}")
    result = await backend_request("DELETE", f"/items/{item_id}", token=auth_token)
    return {"success": True, "deleted_id": item_id, "result": result}


@mcp.tool
async def list_items(
    auth_token: str = Field(default="", description="Authorization token (injected by wrapper)"),
    skip: int = Field(default=0, description="Number of items to skip"),
    limit: int = Field(default=100, description="Maximum items to return")
) -> dict:
    """List all items in the database with pagination."""
    logger.info(f"[list_items] Listing (skip={skip}, limit={limit})")
    items = await backend_request("GET", "/items/", token=auth_token, params={"skip": skip, "limit": limit})
    # Wrap list in dict for FastMCP compatibility
    if isinstance(items, list):
        return {"items": items, "count": len(items)}
    return items


# ============================================================================
# SEARCH TOOLS
# ============================================================================

@mcp.tool
async def search_items(
    query: str = Field(description="Search query string"),
    auth_token: str = Field(default="", description="Authorization token (injected by wrapper)"),
    field: str = Field(default="all", description="Field to search: all, name, description, data"),
    limit: int = Field(default=20, description="Maximum results to return"),
    offset: int = Field(default=0, description="Number of results to skip")
) -> dict:
    """Search items by text query."""
    logger.info(f"[search_items] Searching: {query}")
    result = await backend_request(
        "GET", "/items/search",
        token=auth_token,
        params={"q": query, "field": field, "limit": limit, "offset": offset}
    )
    # Wrap list in dict for FastMCP compatibility
    if isinstance(result, list):
        return {"items": result, "count": len(result), "query": query}
    return result


# ============================================================================
# STATISTICS & REPORTS
# ============================================================================

@mcp.tool
async def get_statistics(
    auth_token: str = Field(default="", description="Authorization token (injected by wrapper)")
) -> dict:
    """Get database statistics including total items and recent activity."""
    logger.info("[get_statistics] Fetching stats")
    return await backend_request("GET", "/items/stats", token=auth_token)


@mcp.tool
async def generate_report(
    report_type: str = Field(description="Type of report: summary, detailed, activity"),
    auth_token: str = Field(default="", description="Authorization token (injected by wrapper)"),
    filters: dict = Field(default_factory=dict, description="Optional filters for the report")
) -> dict:
    """Generate a report based on the specified type and filters."""
    logger.info(f"[generate_report] Generating {report_type} report")
    return await backend_request(
        "POST", "/reports/generate",
        token=auth_token,
        json_data={"report_type": report_type, "filters": filters}
    )


# ============================================================================
# USER TOOLS
# ============================================================================

@mcp.tool
async def get_user_profile(
    auth_token: str = Field(default="", description="Authorization token (injected by wrapper)")
) -> dict:
    """Get the current user's profile information."""
    logger.info("[get_user_profile] Fetching profile")
    return await backend_request("GET", "/users/me", token=auth_token)


@mcp.tool
async def update_user_profile(
    auth_token: str = Field(default="", description="Authorization token (injected by wrapper)"),
    display_name: Optional[str] = Field(default=None, description="New display name"),
    email: Optional[str] = Field(default=None, description="New email address"),
    preferences: Optional[dict] = Field(default=None, description="User preferences")
) -> dict:
    """Update the current user's profile."""
    logger.info("[update_user_profile] Updating profile")
    
    profile_data = {}
    if display_name is not None:
        profile_data["display_name"] = display_name
    if email is not None:
        profile_data["email"] = email
    if preferences is not None:
        profile_data["preferences"] = preferences
    
    return await backend_request("PUT", "/users/me", token=auth_token, json_data=profile_data)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    logger.info(f"🚀 Starting FastMCP Server on port {MCP_SERVER_PORT}")
    logger.info(f"📡 Backend URL: {BACKEND_URL}")
    
    # Run with streamable HTTP transport (recommended for production)
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=MCP_SERVER_PORT
    )
