"""FastMCP Server with token-based authentication.

This is a clean FastMCP implementation that uses:
- @mcp.tool decorators for automatic schema generation
- Native FastMCP framework with streamable-http transport
- Auth token extraction from HTTP request headers (native) or parameter (JSON-RPC wrapper)
"""
import os
import logging
from typing import Optional, Dict, Any

import httpx
from fastmcp import FastMCP, Context
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


def _extract_token_from_context(ctx: Context) -> str:
    """Extract auth token from the MCP request's HTTP headers."""
    try:
        from fastmcp.server.dependencies import get_http_request
        request = get_http_request()
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
    except Exception:
        pass
    return ""


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
            detail = response.json().get("detail", "Insufficient permissions")
            raise PermissionError(f"Permission denied: {detail}")
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
    data: dict = Field(default_factory=dict, description="Additional JSON data"),
    auth_token: str = Field(default="", description="Authorization token (auto-injected)")
) -> dict:
    """Create a new item in the database."""
    token = _extract_token_from_context(ctx) or auth_token
    logger.info(f"[create_item] Creating: {name}")
    return await backend_request(
        "POST", "/items/",
        token=token,
        json_data={"name": name, "description": description, "data": data}
    )


@mcp.tool
async def read_item(
    ctx: Context,
    item_id: str = Field(description="The unique ID of the item to read"),
    auth_token: str = Field(default="", description="Authorization token (auto-injected)")
) -> dict:
    """Read an item from the database by its ID."""
    token = _extract_token_from_context(ctx) or auth_token
    logger.info(f"[read_item] Reading: {item_id}")
    return await backend_request("GET", f"/items/{item_id}", token=token)


@mcp.tool
async def update_item(
    ctx: Context,
    item_id: str = Field(description="The unique ID of the item to update"),
    name: Optional[str] = Field(default=None, description="New name for the item"),
    description: Optional[str] = Field(default=None, description="New description"),
    data: Optional[dict] = Field(default=None, description="New JSON data"),
    auth_token: str = Field(default="", description="Authorization token (auto-injected)")
) -> dict:
    """Update an existing item in the database."""
    token = _extract_token_from_context(ctx) or auth_token
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
    item_id: str = Field(description="The unique ID of the item to delete"),
    auth_token: str = Field(default="", description="Authorization token (auto-injected)")
) -> dict:
    """Delete an item from the database. This action is permanent."""
    token = _extract_token_from_context(ctx) or auth_token
    logger.info(f"[delete_item] Deleting: {item_id}")
    result = await backend_request("DELETE", f"/items/{item_id}", token=token)
    return {"success": True, "deleted_id": item_id, "result": result}


@mcp.tool
async def list_items(
    ctx: Context,
    skip: int = Field(default=0, description="Number of items to skip"),
    limit: int = Field(default=100, description="Maximum items to return"),
    auth_token: str = Field(default="", description="Authorization token (auto-injected)")
) -> dict:
    """List all items in the database with pagination."""
    token = _extract_token_from_context(ctx) or auth_token
    logger.info(f"[list_items] Listing (skip={skip}, limit={limit})")
    items = await backend_request("GET", "/items/", token=token, params={"skip": skip, "limit": limit})
    if isinstance(items, list):
        return {"items": items, "count": len(items)}
    return items


# ============================================================================
# SEARCH TOOLS
# ============================================================================

@mcp.tool
async def search_items(
    ctx: Context,
    query: str = Field(description="Search query string"),
    field: str = Field(default="all", description="Field to search: all, name, description, data"),
    limit: int = Field(default=20, description="Maximum results to return"),
    offset: int = Field(default=0, description="Number of results to skip"),
    auth_token: str = Field(default="", description="Authorization token (auto-injected)")
) -> dict:
    """Search items by text query."""
    token = _extract_token_from_context(ctx) or auth_token
    logger.info(f"[search_items] Searching: {query}")
    result = await backend_request(
        "GET", "/items/search",
        token=token,
        params={"q": query, "field": field, "limit": limit, "offset": offset}
    )
    if isinstance(result, list):
        return {"items": result, "count": len(result), "query": query}
    return result


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
