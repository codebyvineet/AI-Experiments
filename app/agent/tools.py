"""MCP tool integration for LangGraph.

This module provides tool loading and wrapping for MCP server integration.
Tools are loaded dynamically and wrapped to inject authorization tokens.
"""

from typing import List, Dict, Any, Optional, Callable
import httpx
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.config.logging_config import get_logger, LogContext

logger = get_logger("mcp_tools")


class MCPToolWrapper:
    """
    Wraps MCP tools for use with LangGraph.
    
    Handles:
    - Loading tool definitions from MCP server
    - Converting MCP tools to LangChain format
    - Injecting authorization tokens into tool calls
    """
    
    def __init__(self, mcp_server_url: str = "http://mcp-server:8001"):
        self.mcp_server_url = mcp_server_url
        self._tools_cache: Dict[str, Dict[str, Any]] = {}
    
    async def load_tools(self, token: str) -> List[BaseTool]:
        """
        Load all available tools from MCP server.
        
        Args:
            token: JWT token for authorization
            
        Returns:
            List of LangChain tools ready for use in LangGraph
        """
        log = LogContext(logger)
        log.info(f"🔧 Loading tools from MCP server: {self.mcp_server_url}")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.mcp_server_url}/message",
                    json={
                        "jsonrpc": "2.0",
                        "id": "tools-list",
                        "method": "tools/list",
                        "params": {}
                    },
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                
            tools_data = data.get("result", {}).get("tools", [])
            log.info(f"✅ Loaded {len(tools_data)} tools from MCP server")
            
            # Convert to LangChain tools with token injection
            langchain_tools = []
            for tool_def in tools_data:
                wrapped_tool = self._create_tool(tool_def, token)
                langchain_tools.append(wrapped_tool)
                self._tools_cache[tool_def["name"]] = tool_def
            
            return langchain_tools
            
        except Exception as e:
            log.error(f"❌ Failed to load tools: {e}")
            return []
    
    def _create_tool(self, tool_def: Dict[str, Any], token: str) -> BaseTool:
        """Create a LangChain tool from MCP tool definition."""
        name = tool_def["name"]
        description = tool_def.get("description", f"Execute {name}")
        input_schema = tool_def.get("inputSchema", {})
        
        # Create dynamic tool function
        async def tool_func(**kwargs) -> str:
            return await self._call_tool(name, kwargs, token)
        
        # Build Pydantic model for input validation
        fields = {}
        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])
        
        for prop_name, prop_def in properties.items():
            field_type = str  # Default to string
            if prop_def.get("type") == "integer":
                field_type = int
            elif prop_def.get("type") == "boolean":
                field_type = bool
            elif prop_def.get("type") == "object":
                field_type = dict
            elif prop_def.get("type") == "array":
                field_type = list
            
            default = ... if prop_name in required else None
            fields[prop_name] = (field_type, Field(default=default, description=prop_def.get("description", "")))
        
        # Create tool with proper typing
        return StructuredTool.from_function(
            coroutine=tool_func,
            name=name,
            description=description,
            args_schema=self._create_schema(name, fields) if fields else None
        )
    
    def _create_schema(self, name: str, fields: Dict) -> type:
        """Dynamically create a Pydantic model for tool arguments."""
        return type(f"{name}Args", (BaseModel,), {"__annotations__": {k: v[0] for k, v in fields.items()}})
    
    async def _call_tool(self, name: str, arguments: Dict[str, Any], token: str) -> str:
        """Call an MCP tool and return the result."""
        log = LogContext(logger, tool=name)
        log.info(f"[AIFLOW] MCP Tool Called: {name} with params: {arguments}")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.mcp_server_url}/message",
                    json={
                        "jsonrpc": "2.0",
                        "id": f"tool-call-{name}",
                        "method": "tools/call",
                        "params": {
                            "name": name,
                            "arguments": arguments
                        }
                    },
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=60.0
                )
                
                # Handle HTTP errors
                if response.status_code == 401:
                    result = "Authorization failed: Invalid token"
                    log.info(f"[AIFLOW] MCP Tool Result: {name} -> {result}")
                    return result
                elif response.status_code == 403:
                    result = "Authorization failed: Insufficient permissions"
                    log.info(f"[AIFLOW] MCP Tool Result: {name} -> {result}")
                    return result
                
                response.raise_for_status()
                data = response.json()
                
            # Extract result from MCP response
            if "error" in data:
                result = f"Error: {data['error'].get('message', 'Unknown error')}"
            else:
                content = data.get("result", {}).get("content", [])
                if content and len(content) > 0:
                    result = content[0].get("text", str(content))
                else:
                    result = str(data.get("result", {}))
            
            log.info(f"[AIFLOW] MCP Tool Result: {name} -> {result[:200]}...")
            return result
            
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error calling {name}: {e.response.status_code}"
            log.error(f"[AIFLOW] MCP Tool Result: {name} -> {error_msg}")
            return error_msg
        except Exception as e:
            error_msg = f"Error calling {name}: {str(e)}"
            log.error(f"[AIFLOW] MCP Tool Result: {name} -> {error_msg}")
            return error_msg
    
    async def call_tool_direct(self, name: str, arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
        """
        Call an MCP tool directly without going through LangChain.
        
        Returns structured result with status for error handling.
        """
        result_str = await self._call_tool(name, arguments, token)
        
        # Parse result to determine status
        if "Authorization failed" in result_str:
            return {
                "status": "authorization_failed",
                "result": result_str,
                "tool": name
            }
        elif result_str.startswith("Error:") or result_str.startswith("HTTP error"):
            return {
                "status": "failed",
                "result": result_str,
                "tool": name
            }
        else:
            return {
                "status": "success",
                "result": result_str,
                "tool": name
            }


# Global instance
mcp_tool_wrapper = MCPToolWrapper()


async def get_mcp_tools(token: str) -> List[BaseTool]:
    """Get all MCP tools for use in LangGraph."""
    return await mcp_tool_wrapper.load_tools(token)


async def call_mcp_tool(name: str, arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Call an MCP tool directly."""
    return await mcp_tool_wrapper.call_tool_direct(name, arguments, token)
