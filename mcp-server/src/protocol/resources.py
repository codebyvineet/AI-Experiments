"""MCP resources protocol handlers."""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Available resources
RESOURCES = [
    {
        "uri": "items://all",
        "name": "All Items",
        "description": "List of all items in the database",
        "mimeType": "application/json"
    },
    {
        "uri": "stats://overview",
        "name": "Statistics Overview",
        "description": "Overview statistics of items",
        "mimeType": "application/json"
    }
]


async def handle_resources_list(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Handle resources/list request.
    
    Returns list of all available resources.
    """
    logger.info("[MCP Resources] resources/list request")
    logger.info(f"[MCP Resources] Returning {len(RESOURCES)} resources")
    
    return {"resources": RESOURCES}


async def handle_resources_read(params: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Handle resources/read request.
    
    Reads a resource by URI.
    """
    uri = params.get("uri")
    
    logger.info(f"[MCP Resources] resources/read: {uri}")
    
    if not uri:
        raise ValueError("Missing required parameter: uri")
    
    # For now, return a placeholder - actual implementation would fetch data
    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": "application/json",
                "text": "{}"  # Placeholder
            }
        ]
    }
