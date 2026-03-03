"""MCP Client using langchain-mcp-adapters.

This replaces the custom MCP client with the official LangChain adapter,
providing a cleaner interface while maintaining all functionality.

The adapter handles:
- Connection management
- Tool discovery
- JSON-RPC protocol
"""
import os
import json
import logging
from typing import Any, Dict, List, Optional

from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)

# MCP Server URL from environment
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-server:8001")


class MCPClientWrapper:
    """
    MCP Client wrapper using langchain-mcp-adapters.
    
    This provides a clean interface for interacting with the MCP server,
    with per-request authentication token support.
    """
    
    def __init__(self, mcp_server_url: Optional[str] = None):
        self.mcp_server_url = mcp_server_url or MCP_SERVER_URL
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        logger.info(f"[MCP Client] Initialized with server URL: {self.mcp_server_url}")
    
    def _create_client(self, token: Optional[str] = None) -> MultiServerMCPClient:
        """Create a client with optional auth headers."""
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        return MultiServerMCPClient({
            "main": {
                "transport": "streamable_http",
                "url": f"{self.mcp_server_url}/mcp",
                "headers": headers
            }
        })
    
    async def initialize(self, client_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Initialize connection with MCP server (legacy compatibility)."""
        logger.info("[MCP Client] Initializing connection")
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": True}},
            "serverInfo": {"name": "AI-Experiments MCP Server", "version": "2.0.0"}
        }
    
    async def list_tools(self, token: Optional[str] = None, use_cache: bool = True) -> List[Dict[str, Any]]:
        """List available tools from MCP server."""
        if use_cache and self._tools_cache is not None:
            return self._tools_cache
        
        logger.info("[MCP Client] Fetching tools list")
        
        async with self._create_client(token) as client:
            langchain_tools = await client.get_tools()
            
            # Convert LangChain tools to our format
            tools = []
            for tool in langchain_tools:
                tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.args_schema.model_json_schema() if tool.args_schema else {}
                })
            
            self._tools_cache = tools
            logger.info(f"[MCP Client] Retrieved {len(tools)} tools via adapter")
            return tools
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
        """Call a tool on the MCP server via langchain-mcp-adapters."""
        logger.info(f"[MCP Client] Calling tool: {tool_name}")
        
        if not token:
            raise PermissionError("Authorization token required for tool calls")
        
        async with self._create_client(token) as client:
            langchain_tools = await client.get_tools()
            
            # Find the requested tool
            tool = next((t for t in langchain_tools if t.name == tool_name), None)
            if not tool:
                raise ValueError(f"Unknown tool: {tool_name}")
            
            # Execute the tool
            result = await tool.ainvoke(arguments)
            
            # Parse result if it's JSON
            if isinstance(result, str):
                try:
                    return json.loads(result)
                except json.JSONDecodeError:
                    return {"result": result}
            return result if isinstance(result, dict) else {"result": result}
    
    async def list_resources(self, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """List available resources from MCP server."""
        # Resources are not commonly used, return empty list
        return []
    
    async def read_resource(self, uri: str, token: str) -> Dict[str, Any]:
        """Read a resource by URI."""
        raise NotImplementedError("Resources not implemented in this MCP server")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check MCP server health."""
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.mcp_server_url}/health")
            return response.json()
    
    def get_tools_description(self) -> str:
        """Get formatted description of available tools for AI prompts."""
        if not self._tools_cache:
            return "Tools not yet loaded. Call list_tools() first."
        
        descriptions = []
        for tool in self._tools_cache:
            desc = f"- **{tool['name']}**: {tool.get('description', 'No description')}"
            
            input_schema = tool.get("inputSchema", {})
            properties = input_schema.get("properties", {})
            required = input_schema.get("required", [])
            
            if properties:
                param_parts = []
                for name, schema in properties.items():
                    # Skip internal params like 'ctx'
                    if name == 'ctx':
                        continue
                    param_type = schema.get("type", "any")
                    req_marker = " (required)" if name in required else ""
                    param_parts.append(f"{name}: {param_type}{req_marker}")
                if param_parts:
                    desc += f"\n  Parameters: {', '.join(param_parts)}"
            
            descriptions.append(desc)
        
        return "\n".join(descriptions)
    
    def clear_cache(self):
        """Clear the tools cache."""
        self._tools_cache = None
        logger.info("[MCP Client] Cache cleared")


# Global client instance
mcp_client = MCPClientWrapper()


# Compatibility function
async def get_mcp_tools_description() -> str:
    """Get MCP tools description for AI prompts."""
    try:
        if not mcp_client._tools_cache:
            await mcp_client.list_tools()
        return mcp_client.get_tools_description()
    except Exception as e:
        logger.error(f"[MCP Client] Failed to get tools description: {e}")
        return f"Error loading MCP tools: {e}"


# For backward compatibility
MCPClient = MCPClientWrapper
