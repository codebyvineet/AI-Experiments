"""Tool registry for MCP Server.

All tools are registered here and executed through the Backend API.
"""
import logging
import json
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Tool registry: name -> tool definition
_TOOLS: Dict[str, Dict[str, Any]] = {}

# Tool handlers: name -> async handler function
_HANDLERS: Dict[str, Callable] = {}


def register_tool(
    name: str,
    description: str,
    input_schema: Dict[str, Any],
    handler: Callable
) -> None:
    """Register a tool with its handler.
    
    Args:
        name: Tool name (unique identifier)
        description: Human-readable description of what the tool does
        input_schema: JSON Schema for the tool's input parameters
        handler: Async function that executes the tool
    """
    logger.info(f"[Tool Registry] Registering tool: {name}")
    
    _TOOLS[name] = {
        "name": name,
        "description": description,
        "inputSchema": input_schema
    }
    _HANDLERS[name] = handler


def list_all_tools() -> List[Dict[str, Any]]:
    """List all registered tools with their schemas."""
    return list(_TOOLS.values())


def get_tool(name: str) -> Optional[Dict[str, Any]]:
    """Get a tool definition by name."""
    return _TOOLS.get(name)


async def call_tool(name: str, arguments: Dict[str, Any], token: str) -> Any:
    """Call a tool by name with the provided arguments.
    
    Args:
        name: Tool name
        arguments: Tool arguments
        token: Authorization token for Backend API
        
    Returns:
        Tool execution result
        
    Raises:
        ValueError: If tool is not found
    """
    if name not in _HANDLERS:
        logger.error(f"[Tool Registry] Unknown tool: {name}")
        raise ValueError(f"Unknown tool: {name}")
    
    handler = _HANDLERS[name]
    logger.info(f"[Tool Registry] Executing tool: {name}")
    logger.debug(f"[Tool Registry] Arguments: {arguments}")
    
    result = await handler(arguments, token)
    
    # Convert to JSON string if it's a dict
    if isinstance(result, dict):
        return json.dumps(result, indent=2, default=str)
    
    return result


def get_tools_description() -> str:
    """Get a formatted description of all tools for AI context."""
    descriptions = []
    for tool in _TOOLS.values():
        desc = f"- **{tool['name']}**: {tool['description']}"
        if tool.get('inputSchema', {}).get('properties'):
            params = tool['inputSchema']['properties']
            param_desc = ", ".join(f"{k}: {v.get('type', 'any')}" for k, v in params.items())
            desc += f"\n  Parameters: {param_desc}"
        descriptions.append(desc)
    return "\n".join(descriptions)
