"""MCP package - Client for external MCP Server.

This package provides the MCP Client for communicating with the
external MCP Server container via JSON-RPC over HTTP.

Architecture:
  Backend App → MCP Client → HTTP → MCP Server (separate container) → Backend API
"""

from app.mcp.client import mcp_client, MCPClient, get_mcp_tools_description

__all__ = ["mcp_client", "MCPClient", "get_mcp_tools_description"]
