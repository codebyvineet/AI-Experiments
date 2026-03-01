"""Item CRUD tools for MCP Server.

All operations go through Backend API with authorization.
"""
import logging
from typing import Any, Dict, Optional
from .registry import register_tool
from ..backend_client import backend_client

logger = logging.getLogger(__name__)


# Tool: create_item
async def handle_create_item(arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Create a new item."""
    name = arguments.get("name")
    description = arguments.get("description", "")
    data = arguments.get("data", {})
    
    if not name:
        raise ValueError("Missing required parameter: name")
    
    logger.info(f"[create_item] Creating item: {name}")
    result = await backend_client.create_item(token, name, description, data)
    return result


register_tool(
    name="create_item",
    description="Create a new item in the database. Use this to add new records with a name, description, and optional JSON data.",
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The name of the item (required)"
            },
            "description": {
                "type": "string",
                "description": "A description of the item (optional)"
            },
            "data": {
                "type": "object",
                "description": "Additional JSON data to store with the item (optional)"
            }
        },
        "required": ["name"]
    },
    handler=handle_create_item,
    category="items",
    tags=["crud", "write", "create"],
    permissions=["items:write"],
    endpoint="/items/",
    http_method="POST"
)


# Tool: read_item
async def handle_read_item(arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Read an item by ID."""
    item_id = arguments.get("item_id")
    
    if not item_id:
        raise ValueError("Missing required parameter: item_id")
    
    logger.info(f"[read_item] Reading item: {item_id}")
    result = await backend_client.read_item(token, item_id)
    return result


register_tool(
    name="read_item",
    description="Read an item from the database by its ID. Returns the item's name, description, data, and metadata.",
    input_schema={
        "type": "object",
        "properties": {
            "item_id": {
                "type": "string",
                "description": "The unique ID of the item to read (required)"
            }
        },
        "required": ["item_id"]
    },
    handler=handle_read_item,
    category="items",
    tags=["crud", "read", "get"],
    permissions=["items:read"],
    endpoint="/items/{item_id}",
    http_method="GET"
)


# Tool: update_item
async def handle_update_item(arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Update an existing item."""
    item_id = arguments.get("item_id")
    name = arguments.get("name")
    description = arguments.get("description")
    data = arguments.get("data")
    
    if not item_id:
        raise ValueError("Missing required parameter: item_id")
    
    logger.info(f"[update_item] Updating item: {item_id}")
    result = await backend_client.update_item(token, item_id, name, description, data)
    return result


register_tool(
    name="update_item",
    description="Update an existing item in the database. You can update the name, description, and/or data fields.",
    input_schema={
        "type": "object",
        "properties": {
            "item_id": {
                "type": "string",
                "description": "The unique ID of the item to update (required)"
            },
            "name": {
                "type": "string",
                "description": "New name for the item (optional)"
            },
            "description": {
                "type": "string",
                "description": "New description for the item (optional)"
            },
            "data": {
                "type": "object",
                "description": "New JSON data for the item (optional, replaces existing data)"
            }
        },
        "required": ["item_id"]
    },
    handler=handle_update_item,
    category="items",
    tags=["crud", "write", "update"],
    permissions=["items:write"],
    endpoint="/items/{item_id}",
    http_method="PUT"
)


# Tool: delete_item
async def handle_delete_item(arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Delete an item."""
    item_id = arguments.get("item_id")
    
    if not item_id:
        raise ValueError("Missing required parameter: item_id")
    
    logger.info(f"[delete_item] Deleting item: {item_id}")
    result = await backend_client.delete_item(token, item_id)
    return {"success": True, "deleted_id": item_id, "result": result}


register_tool(
    name="delete_item",
    description="Delete an item from the database by its ID. This action is permanent.",
    input_schema={
        "type": "object",
        "properties": {
            "item_id": {
                "type": "string",
                "description": "The unique ID of the item to delete (required)"
            }
        },
        "required": ["item_id"]
    },
    handler=handle_delete_item,
    category="items",
    tags=["crud", "write", "delete"],
    permissions=["items:delete"],
    endpoint="/items/{item_id}",
    http_method="DELETE"
)


# Tool: list_items
async def handle_list_items(arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
    """List all items."""
    skip = arguments.get("skip", 0)
    limit = arguments.get("limit", 100)
    
    logger.info(f"[list_items] Listing items (skip={skip}, limit={limit})")
    result = await backend_client.list_items(token, skip, limit)
    return result


register_tool(
    name="list_items",
    description="List all items in the database with pagination. Returns an array of items.",
    input_schema={
        "type": "object",
        "properties": {
            "skip": {
                "type": "integer",
                "description": "Number of items to skip (for pagination, default: 0)"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of items to return (default: 100)"
            }
        },
        "required": []
    },
    handler=handle_list_items,
    category="items",
    tags=["crud", "read", "list"],
    permissions=["items:read"],
    endpoint="/items/",
    http_method="GET"
)
