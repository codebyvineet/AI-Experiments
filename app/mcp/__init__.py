"""MCP client package — thin wrappers around langchain-mcp-adapters."""

from app.mcp.client import create_mcp_client, list_mcp_tools, call_mcp_tool, mcp_health_check

__all__ = ["create_mcp_client", "list_mcp_tools", "call_mcp_tool", "mcp_health_check"]
