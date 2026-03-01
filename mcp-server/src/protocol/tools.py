"""MCP tools protocol handlers."""
import logging
from typing import Any, Dict, List, Optional
from ..tools.registry import list_all_tools, call_tool

logger = logging.getLogger(__name__)


async def handle_tools_list(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Handle tools/list request.
    
    Returns list of all available tools with their schemas.
    """
    logger.info("[MCP Tools] tools/list request")
    
    tools = list_all_tools()
    
    logger.info(f"[MCP Tools] Returning {len(tools)} tools")
    for tool in tools:
        logger.debug(f"[MCP Tools]   - {tool['name']}: {tool['description'][:50]}...")
    
    return {"tools": tools}


async def handle_tools_call(params: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Handle tools/call request.
    
    Executes a tool with the provided arguments.
    
    Args:
        params: Must contain 'name' and optionally 'arguments'
        token: Authorization token for Backend API calls
        
    Returns:
        Tool execution result wrapped in MCP format
    """
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    
    logger.info(f"[MCP Tools] tools/call: {tool_name}")
    logger.info(f"[MCP Tools] Arguments: {arguments}")
    
    if not tool_name:
        logger.error("[MCP Tools] Missing tool name")
        raise ValueError("Missing required parameter: name")
    
    try:
        result = await call_tool(tool_name, arguments, token)
        logger.info(f"[MCP Tools] Tool {tool_name} completed successfully")
        logger.debug(f"[MCP Tools] Result: {result}")
        
        # Return in MCP format
        return {
            "content": [
                {
                    "type": "text",
                    "text": str(result) if not isinstance(result, str) else result
                }
            ],
            "isError": False
        }
    except PermissionError as e:
        logger.error(f"[MCP Tools] Permission error: {e}")
        return {
            "content": [{"type": "text", "text": f"Authorization error: {str(e)}"}],
            "isError": True
        }
    except ValueError as e:
        logger.error(f"[MCP Tools] Value error: {e}")
        return {
            "content": [{"type": "text", "text": f"Invalid parameters: {str(e)}"}],
            "isError": True
        }
    except Exception as e:
        logger.error(f"[MCP Tools] Tool execution error: {e}")
        return {
            "content": [{"type": "text", "text": f"Tool execution failed: {str(e)}"}],
            "isError": True
        }
