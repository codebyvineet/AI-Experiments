"""MCP lifecycle management (initialize, shutdown)."""
import logging
from typing import Any, Dict
from ..config import settings

logger = logging.getLogger(__name__)


# Server capabilities
SERVER_CAPABILITIES = {
    "tools": {
        "listChanged": True  # Server supports tools/list_changed notification
    },
    "resources": {
        "subscribe": False,  # Server doesn't support resource subscriptions yet
        "listChanged": True
    },
    "prompts": {
        "listChanged": False  # Not implementing prompts for now
    },
    "logging": {}  # Server supports logging
}

# Server info
SERVER_INFO = {
    "name": settings.SERVER_NAME,
    "version": settings.SERVER_VERSION
}


async def handle_initialize(params: Dict[str, Any]) -> Dict[str, Any]:
    """Handle initialize request from client.
    
    This is the first message in the MCP lifecycle.
    Client sends its capabilities, server responds with its capabilities.
    """
    logger.info("[MCP Lifecycle] Initialize request received")
    logger.info(f"[MCP Lifecycle] Client protocol version: {params.get('protocolVersion')}")
    logger.info(f"[MCP Lifecycle] Client info: {params.get('clientInfo')}")
    logger.info(f"[MCP Lifecycle] Client capabilities: {params.get('capabilities')}")
    
    # Validate protocol version
    client_version = params.get("protocolVersion", "")
    if client_version and client_version != settings.PROTOCOL_VERSION:
        logger.warning(f"[MCP Lifecycle] Protocol version mismatch: client={client_version}, server={settings.PROTOCOL_VERSION}")
    
    # Store client info for session (could be used for capability negotiation)
    client_info = params.get("clientInfo", {})
    client_capabilities = params.get("capabilities", {})
    
    response = {
        "protocolVersion": settings.PROTOCOL_VERSION,
        "capabilities": SERVER_CAPABILITIES,
        "serverInfo": SERVER_INFO
    }
    
    logger.info(f"[MCP Lifecycle] Initialize response: {response}")
    return response


async def handle_initialized() -> None:
    """Handle initialized notification from client.
    
    This notification indicates the client has processed the initialize response.
    After this, normal operations can begin.
    """
    logger.info("[MCP Lifecycle] Client sent 'initialized' notification - ready for operations")


async def handle_shutdown() -> Dict[str, Any]:
    """Handle shutdown request.
    
    Client is requesting graceful shutdown.
    """
    logger.info("[MCP Lifecycle] Shutdown request received")
    return {"success": True}


async def handle_ping() -> Dict[str, Any]:
    """Handle ping request for health checks."""
    logger.debug("[MCP Lifecycle] Ping received")
    return {}
