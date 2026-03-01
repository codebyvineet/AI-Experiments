"""Search tools for MCP Server."""
import logging
from typing import Any, Dict
from .registry import register_tool
from ..backend_client import backend_client

logger = logging.getLogger(__name__)


# Tool: search_items
async def handle_search_items(arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Search items by query."""
    query = arguments.get("query", arguments.get("q", ""))
    field = arguments.get("field", "all")
    limit = arguments.get("limit", 20)
    offset = arguments.get("offset", 0)
    
    if not query:
        raise ValueError("Missing required parameter: query")
    
    logger.info(f"[search_items] Searching for: {query} in field: {field}")
    result = await backend_client.search_items(token, query, field, limit, offset)
    return result


register_tool(
    name="search_items",
    description="Search for items by text query. Can search across all fields or a specific field (name, description, data).",
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query text (required)"
            },
            "field": {
                "type": "string",
                "enum": ["all", "name", "description", "data"],
                "description": "Field to search in (default: all)"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (default: 20)"
            },
            "offset": {
                "type": "integer",
                "description": "Number of results to skip (default: 0)"
            }
        },
        "required": ["query"]
    },
    handler=handle_search_items
)
