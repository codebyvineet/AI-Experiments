"""FastMCP Server with native authentication support.

This is a clean FastMCP implementation that uses:
- FastMCP Context for accessing request headers (auth tokens)
- @mcp.tool decorators for automatic schema generation
- Native streamable-http transport

No custom FastAPI wrapper needed - FastMCP handles everything.
"""
import os
import logging
from typing import Optional, List, Dict, Any

import httpx
from fastmcp import FastMCP
from pydantic import Field

# Import Context for type hints (optional - we use duck typing)
try:
    from fastmcp import Context
except ImportError:
    Context = Any  # type: ignore

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://app:8000")
MCP_SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "8001"))


async def get_token_from_context(ctx) -> str:
    """Extract Bearer token from Context or MockContext.
    
    Works with:
    - FastMCP's native Context (when using streamable-http transport)
    - MockContext from app.py (when using JSON-RPC wrapper)
    """
    try:
        # Check for MockContext (from app.py wrapper)
        if hasattr(ctx, '_token'):
            return ctx._token
        
        # Check for request.headers (MockContext style)
        if hasattr(ctx, 'request') and hasattr(ctx.request, 'headers'):
            headers = ctx.request.headers
            if isinstance(headers, dict):
                auth_header = headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    return auth_header[7:]
        
        # Check for request_context.meta (alternative)
        if hasattr(ctx, 'request_context'):
            meta = getattr(ctx.request_context, 'meta', {})
            if 'token' in meta:
                return meta['token']
        
        # FastMCP native Context
        if hasattr(ctx, 'request') and hasattr(ctx.request, 'headers'):
            # Try case-insensitive lookup
            auth_header = ""
            headers = ctx.request.headers
            if hasattr(headers, 'get'):
                auth_header = headers.get("authorization") or headers.get("Authorization") or ""
            if auth_header.startswith("Bearer "):
                return auth_header[7:]
                
    except Exception as e:
        logger.warning(f"Error extracting token: {e}")
    
    raise PermissionError("No authorization token provided. Include 'Authorization: Bearer <token>' header.")


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
    ctx: Context,
    name: str = Field(description="The name of the item (required)"),
    description: str = Field(default="", description="A description of the item"),
    data: dict = Field(default_factory=dict, description="Additional JSON data")
) -> dict:
    """Create a new item in the database."""
    token = await get_token_from_context(ctx)
    logger.info(f"[create_item] Creating: {name}")
    return await backend_request(
        "POST", "/items/",
        token=token,
        json_data={"name": name, "description": description, "data": data}
    )


@mcp.tool
async def read_item(
    ctx: Context,
    item_id: str = Field(description="The unique ID of the item to read")
) -> dict:
    """Read an item from the database by its ID."""
    token = await get_token_from_context(ctx)
    logger.info(f"[read_item] Reading: {item_id}")
    return await backend_request("GET", f"/items/{item_id}", token=token)


@mcp.tool
async def update_item(
    ctx: Context,
    item_id: str = Field(description="The unique ID of the item to update"),
    name: Optional[str] = Field(default=None, description="New name for the item"),
    description: Optional[str] = Field(default=None, description="New description"),
    data: Optional[dict] = Field(default=None, description="New JSON data")
) -> dict:
    """Update an existing item in the database."""
    token = await get_token_from_context(ctx)
    logger.info(f"[update_item] Updating: {item_id}")
    
    update_data = {}
    if name is not None:
        update_data["name"] = name
    if description is not None:
        update_data["description"] = description
    if data is not None:
        update_data["data"] = data
    
    return await backend_request("PUT", f"/items/{item_id}", token=token, json_data=update_data)


@mcp.tool
async def delete_item(
    ctx: Context,
    item_id: str = Field(description="The unique ID of the item to delete")
) -> dict:
    """Delete an item from the database. This action is permanent."""
    token = await get_token_from_context(ctx)
    logger.info(f"[delete_item] Deleting: {item_id}")
    result = await backend_request("DELETE", f"/items/{item_id}", token=token)
    return {"success": True, "deleted_id": item_id, "result": result}


@mcp.tool
async def list_items(
    ctx: Context,
    skip: int = Field(default=0, description="Number of items to skip"),
    limit: int = Field(default=100, description="Maximum items to return")
) -> dict:
    """List all items in the database with pagination."""
    token = await get_token_from_context(ctx)
    logger.info(f"[list_items] Listing (skip={skip}, limit={limit})")
    return await backend_request("GET", "/items/", token=token, params={"skip": skip, "limit": limit})


# ============================================================================
# SEARCH TOOLS
# ============================================================================

@mcp.tool
async def search_items(
    ctx: Context,
    query: str = Field(description="Search query string"),
    field: str = Field(default="all", description="Field to search: all, name, description, data"),
    limit: int = Field(default=20, description="Maximum results to return"),
    offset: int = Field(default=0, description="Number of results to skip")
) -> dict:
    """Search items by text query."""
    token = await get_token_from_context(ctx)
    logger.info(f"[search_items] Searching: {query}")
    return await backend_request(
        "GET", "/items/search",
        token=token,
        params={"q": query, "field": field, "limit": limit, "offset": offset}
    )


# ============================================================================
# BATCH OPERATIONS
# ============================================================================

@mcp.tool
async def bulk_create(
    ctx: Context,
    items: List[dict] = Field(description="Array of items to create, each with name, description, data")
) -> dict:
    """Create multiple items at once."""
    token = await get_token_from_context(ctx)
    logger.info(f"[bulk_create] Creating {len(items)} items")
    return await backend_request("POST", "/items/batch/create", token=token, json_data={"items": items})


@mcp.tool
async def bulk_delete(
    ctx: Context,
    item_ids: List[str] = Field(description="Array of item IDs to delete")
) -> dict:
    """Delete multiple items by their IDs."""
    token = await get_token_from_context(ctx)
    logger.info(f"[bulk_delete] Deleting {len(item_ids)} items")
    return await backend_request("POST", "/items/batch/delete", token=token, json_data={"item_ids": item_ids})


# ============================================================================
# STATISTICS & REPORTS
# ============================================================================

@mcp.tool
async def get_statistics(ctx: Context) -> dict:
    """Get database statistics including total items and recent activity."""
    token = await get_token_from_context(ctx)
    logger.info("[get_statistics] Fetching stats")
    return await backend_request("GET", "/items/stats", token=token)


@mcp.tool
async def generate_report(
    ctx: Context,
    report_type: str = Field(description="Type of report: summary, detailed, activity"),
    filters: dict = Field(default_factory=dict, description="Optional filters for the report")
) -> dict:
    """Generate a report based on the specified type and filters."""
    token = await get_token_from_context(ctx)
    logger.info(f"[generate_report] Generating {report_type} report")
    return await backend_request(
        "POST", "/reports/generate",
        token=token,
        json_data={"report_type": report_type, "filters": filters}
    )


# ============================================================================
# USER TOOLS
# ============================================================================

@mcp.tool
async def get_user_profile(ctx: Context) -> dict:
    """Get the current user's profile information."""
    token = await get_token_from_context(ctx)
    logger.info("[get_user_profile] Fetching profile")
    return await backend_request("GET", "/users/me", token=token)


@mcp.tool
async def update_user_profile(
    ctx: Context,
    display_name: Optional[str] = Field(default=None, description="New display name"),
    email: Optional[str] = Field(default=None, description="New email address"),
    preferences: Optional[dict] = Field(default=None, description="User preferences")
) -> dict:
    """Update the current user's profile."""
    token = await get_token_from_context(ctx)
    logger.info("[update_user_profile] Updating profile")
    
    profile_data = {}
    if display_name is not None:
        profile_data["display_name"] = display_name
    if email is not None:
        profile_data["email"] = email
    if preferences is not None:
        profile_data["preferences"] = preferences
    
    return await backend_request("PUT", "/users/me", token=token, json_data=profile_data)


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
