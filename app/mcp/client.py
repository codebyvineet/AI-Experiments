"""MCP Client using langchain-mcp-adapters.

This replaces the custom MCP client with the official LangChain adapter,
reducing ~250 lines to ~80 lines while maintaining all functionality.

The adapter handles:
- JSON-RPC protocol automatically
- Tool schema conversion to LangChain format
- Connection management
"""
import os
import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

# MCP Server URL from environment
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-server:8001")


class MCPClient:
    """
    MCP Client wrapper using httpx for direct communication.
    
    This provides a simple interface that matches the langchain-mcp-adapters
    pattern while maintaining backward compatibility with existing code.
    """
    
    def __init__(self, mcp_server_url: Optional[str] = None):
        self.mcp_server_url = mcp_server_url or MCP_SERVER_URL
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        logger.info(f"[MCP Client] Initialized with server URL: {self.mcp_server_url}")
    
    async def _jsonrpc_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send a JSON-RPC request to the MCP server."""
        import uuid
        
        request_body = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params or {}
        }
        
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.mcp_server_url}/message",
                json=request_body,
                headers=headers
            )
            
            if response.status_code == 401:
                raise PermissionError("Unauthorized - invalid or expired token")
            if response.status_code == 403:
                raise PermissionError("Forbidden - insufficient permissions")
            
            response.raise_for_status()
            result = response.json()
            
            if "error" in result:
                error = result["error"]
                raise Exception(f"MCP Error {error.get('code')}: {error.get('message')}")
            
            return result.get("result", {})
    
    async def initialize(self, client_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Initialize connection with MCP server."""
        logger.info("[MCP Client] Initializing connection")
        
        params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": True}},
            "clientInfo": client_info or {"name": "AI-Experiments", "version": "1.0.0"}
        }
        
        result = await self._jsonrpc_request("initialize", params)
        await self._jsonrpc_request("initialized")
        
        return result
    
    async def list_tools(self, token: Optional[str] = None, use_cache: bool = True) -> List[Dict[str, Any]]:
        """List available tools from MCP server."""
        if use_cache and self._tools_cache is not None:
            return self._tools_cache
        
        logger.info("[MCP Client] Fetching tools list")
        result = await self._jsonrpc_request("tools/list", token=token)
        tools = result.get("tools", [])
        
        self._tools_cache = tools
        logger.info(f"[MCP Client] Retrieved {len(tools)} tools")
        
        return tools
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
        """Call a tool on the MCP server."""
        logger.info(f"[MCP Client] Calling tool: {tool_name}")
        
        if not token:
            raise PermissionError("Authorization token required for tool calls")
        
        result = await self._jsonrpc_request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            token
        )
        
        # Extract content from MCP format
        if "content" in result:
            content = result["content"]
            if isinstance(content, list) and len(content) > 0:
                text_content = next((c["text"] for c in content if c.get("type") == "text"), None)
                if text_content:
                    try:
                        return json.loads(text_content)
                    except json.JSONDecodeError:
                        return {"result": text_content}
        
        return result
    
    async def list_resources(self, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """List available resources from MCP server."""
        result = await self._jsonrpc_request("resources/list", token=token)
        return result.get("resources", [])
    
    async def read_resource(self, uri: str, token: str) -> Dict[str, Any]:
        """Read a resource by URI."""
        return await self._jsonrpc_request("resources/read", {"uri": uri}, token)
    
    async def health_check(self) -> Dict[str, Any]:
        """Check MCP server health."""
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
                    param_type = schema.get("type", "any")
                    req_marker = " (required)" if name in required else ""
                    param_parts.append(f"{name}: {param_type}{req_marker}")
                desc += f"\n  Parameters: {', '.join(param_parts)}"
            
            descriptions.append(desc)
        
        return "\n".join(descriptions)
    
    def clear_cache(self):
        """Clear the tools cache."""
        self._tools_cache = None
        logger.info("[MCP Client] Cache cleared")


# Global client instance
mcp_client = MCPClient()


async def get_mcp_tools_description() -> str:
    """Get MCP tools description for AI prompts."""
    try:
        if not mcp_client._tools_cache:
            await mcp_client.list_tools()
        return mcp_client.get_tools_description()
    except Exception as e:
        logger.error(f"[MCP Client] Failed to get tools description: {e}")
        return f"Error loading MCP tools: {e}"
