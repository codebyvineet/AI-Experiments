"""MCP Client helpers using langchain-mcp-adapters.

Thin wrappers around MultiServerMCPClient — the framework handles
connection management, JSON-RPC protocol, and tool discovery.
"""

import os
import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-server:8001")


def create_mcp_client(token: Optional[str] = None) -> MultiServerMCPClient:
    """Create a MultiServerMCPClient with optional auth."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return MultiServerMCPClient({
        "main": {
            "transport": "streamable_http",
            "url": f"{MCP_SERVER_URL}/mcp",
            "headers": headers,
        }
    })


async def list_mcp_tools(token: Optional[str] = None) -> List[Dict[str, Any]]:
    """List available tools from MCP server as plain dicts."""
    client = create_mcp_client(token)
    tools = await client.get_tools()
    result = []
    for t in tools:
        schema = t.args_schema
        if hasattr(schema, "model_json_schema"):
            schema = schema.model_json_schema()
        elif not isinstance(schema, dict):
            schema = {}
        result.append({"name": t.name, "description": t.description, "inputSchema": schema})
    return result


async def call_mcp_tool(tool_name: str, arguments: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Call a specific MCP tool by name. Raises ValueError if tool not found."""
    if not token:
        raise PermissionError("Authorization token required for tool calls")

    client = create_mcp_client(token)
    tools = await client.get_tools()
    tool = next((t for t in tools if t.name == tool_name), None)
    if not tool:
        raise ValueError(f"Unknown tool: {tool_name}")

    result = await tool.ainvoke(arguments)

    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"result": result}
    return result if isinstance(result, dict) else {"result": result}


async def mcp_health_check() -> Dict[str, Any]:
    """Check MCP server health via HTTP."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{MCP_SERVER_URL}/health")
        return response.json()
