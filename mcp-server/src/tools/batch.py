"""Batch operation tools for MCP Server."""
import logging
from typing import Any, Dict, List
from .registry import register_tool
from ..backend_client import backend_client

logger = logging.getLogger(__name__)


# Tool: bulk_create
async def handle_bulk_create(arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Bulk create multiple items."""
    items = arguments.get("items", [])
    
    if not items:
        raise ValueError("Missing required parameter: items (must be a non-empty list)")
    
    logger.info(f"[bulk_create] Creating {len(items)} items")
    result = await backend_client.bulk_create(token, items)
    return result


register_tool(
    name="bulk_create",
    description="Create multiple items in a single operation. More efficient than creating items one by one.",
    input_schema={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "Array of items to create",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "data": {"type": "object"}
                    },
                    "required": ["name"]
                }
            }
        },
        "required": ["items"]
    },
    handler=handle_bulk_create
)


# Tool: bulk_delete
async def handle_bulk_delete(arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Bulk delete multiple items."""
    item_ids = arguments.get("item_ids", [])
    
    if not item_ids:
        raise ValueError("Missing required parameter: item_ids (must be a non-empty list)")
    
    logger.info(f"[bulk_delete] Deleting {len(item_ids)} items")
    result = await backend_client.bulk_delete(token, item_ids)
    return result


register_tool(
    name="bulk_delete",
    description="Delete multiple items in a single operation by their IDs.",
    input_schema={
        "type": "object",
        "properties": {
            "item_ids": {
                "type": "array",
                "description": "Array of item IDs to delete",
                "items": {"type": "string"}
            }
        },
        "required": ["item_ids"]
    },
    handler=handle_bulk_delete
)
