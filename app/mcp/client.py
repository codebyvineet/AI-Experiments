"""MCP Client for Backend to connect to external MCP Server.

This client implements the MCP protocol to communicate with the
external MCP Server container via HTTP/JSON-RPC.
"""
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

# MCP Server URL from environment
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-server:8001")


class MCPClient:
    """Client for connecting to external MCP Server via JSON-RPC."""
    
    def __init__(self, mcp_server_url: Optional[str] = None):
        self.mcp_server_url = mcp_server_url or MCP_SERVER_URL
        self._initialized = False
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        logger.info(f"[MCP Client] Initialized with server URL: {self.mcp_server_url}")
    
    async def _send_request(self, method: str, params: Optional[Dict[str, Any]] = None, 
                           token: Optional[str] = None) -> Dict[str, Any]:
        """Send a JSON-RPC request to the MCP server.
        
        Args:
            method: JSON-RPC method name
            params: Method parameters
            token: Authorization token
            
        Returns:
            Response result
        """
        request_id = str(uuid.uuid4())
        
        request_body = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": request_id
        }
        
        logger.info(f"[MCP Client] Sending request: method={method}, id={request_id}")
        logger.debug(f"[MCP Client] Request body: {json.dumps(request_body)}")
        
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.mcp_server_url}/message",
                json=request_body,
                headers=headers
            )
            
            logger.info(f"[MCP Client] Response status: {response.status_code}")
            
            if response.status_code == 401:
                raise PermissionError("Unauthorized - invalid or expired token")
            
            if response.status_code >= 400:
                response.raise_for_status()
            
            result = response.json()
            logger.debug(f"[MCP Client] Response: {json.dumps(result)}")
            
            # Check for JSON-RPC error
            if "error" in result:
                error = result["error"]
                raise Exception(f"MCP Error {error.get('code')}: {error.get('message')}")
            
            return result.get("result", {})
    
    async def initialize(self, client_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Initialize connection with MCP server.
        
        This is the first step in the MCP lifecycle.
        """
        logger.info("[MCP Client] Initializing connection to MCP server")
        
        params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": False, "listChanged": True}
            },
            "clientInfo": client_info or {
                "name": "AI-Experiments Backend",
                "version": "1.0.0"
            }
        }
        
        result = await self._send_request("initialize", params)
        self._initialized = True
        
        logger.info(f"[MCP Client] Server info: {result.get('serverInfo')}")
        logger.info(f"[MCP Client] Server capabilities: {result.get('capabilities')}")
        
        # Send initialized notification
        await self._send_request("initialized")
        
        return result
    
    async def list_tools(self, token: Optional[str] = None, use_cache: bool = True) -> List[Dict[str, Any]]:
        """List available tools from MCP server.
        
        Args:
            token: Authorization token (optional for listing)
            use_cache: Whether to use cached tools list
            
        Returns:
            List of tool definitions
        """
        if use_cache and self._tools_cache is not None:
            logger.debug("[MCP Client] Returning cached tools list")
            return self._tools_cache
        
        logger.info("[MCP Client] Fetching tools list from MCP server")
        
        result = await self._send_request("tools/list", token=token)
        tools = result.get("tools", [])
        
        self._tools_cache = tools
        logger.info(f"[MCP Client] Retrieved {len(tools)} tools")
        for tool in tools:
            logger.debug(f"[MCP Client]   - {tool['name']}: {tool.get('description', '')[:50]}...")
        
        return tools
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
        """Call a tool on the MCP server.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            token: Authorization token (required)
            
        Returns:
            Tool execution result
        """
        logger.info(f"[MCP Client] Calling tool: {tool_name}")
        logger.info(f"[MCP Client] Arguments: {json.dumps(arguments)}")
        
        if not token:
            raise PermissionError("Authorization token required for tool calls")
        
        params = {
            "name": tool_name,
            "arguments": arguments
        }
        
        result = await self._send_request("tools/call", params, token)
        
        logger.info(f"[MCP Client] Tool {tool_name} result received")
        logger.debug(f"[MCP Client] Result: {json.dumps(result)}")
        
        # Extract content from MCP format
        if "content" in result:
            content = result["content"]
            if isinstance(content, list) and len(content) > 0:
                # Get text content
                text_content = next((c["text"] for c in content if c.get("type") == "text"), None)
                if text_content:
                    # Try to parse as JSON
                    try:
                        return json.loads(text_content)
                    except json.JSONDecodeError:
                        return {"result": text_content}
        
        return result
    
    async def list_resources(self, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """List available resources from MCP server."""
        logger.info("[MCP Client] Fetching resources list")
        result = await self._send_request("resources/list", token=token)
        return result.get("resources", [])
    
    async def read_resource(self, uri: str, token: str) -> Dict[str, Any]:
        """Read a resource by URI."""
        logger.info(f"[MCP Client] Reading resource: {uri}")
        result = await self._send_request("resources/read", {"uri": uri}, token)
        return result
    
    async def health_check(self) -> Dict[str, Any]:
        """Check MCP server health."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.mcp_server_url}/health")
            return response.json()
    
    def get_tools_description(self) -> str:
        """Get formatted description of available tools for AI prompts.
        
        Returns cached tools formatted as a string description.
        """
        if not self._tools_cache:
            return "Tools not yet loaded. Call list_tools() first."
        
        descriptions = []
        for tool in self._tools_cache:
            desc = f"- **{tool['name']}**: {tool.get('description', 'No description')}"
            
            # Add parameters info
            input_schema = tool.get("inputSchema", {})
            properties = input_schema.get("properties", {})
            required = input_schema.get("required", [])
            
            if properties:
                param_parts = []
                for name, schema in properties.items():
                    param_type = schema.get("type", "any")
                    is_required = name in required
                    req_marker = " (required)" if is_required else ""
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
    """Get MCP tools description for AI prompts.
    
    This function ensures tools are loaded and returns their description.
    """
    try:
        if not mcp_client._tools_cache:
            await mcp_client.list_tools()
        return mcp_client.get_tools_description()
    except Exception as e:
        logger.error(f"[MCP Client] Failed to get tools description: {e}")
        return f"Error loading MCP tools: {e}"
