"""Standalone FastMCP runner.

Starts the FastMCP SSE server directly (no FastAPI wrapper needed).
The ADK agent connects to ``http://mcp-server:8001/sse`` via
``SseConnectionParams``.
"""

import os
from server import mcp  # type: ignore


if __name__ == "__main__":
    host = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_SERVER_PORT", "8001"))
    # FastMCP's run() starts uvicorn with the SSE transport.
    # Default SSE endpoint: GET /sse — this is what ADK MCPToolset connects to.
    mcp.run(transport="sse", host=host, port=port)
