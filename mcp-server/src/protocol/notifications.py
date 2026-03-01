"""MCP notifications handlers."""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def create_progress_notification(progress: int, total: int, message: str = "") -> Dict[str, Any]:
    """Create a progress notification."""
    return {
        "jsonrpc": "2.0",
        "method": "notifications/progress",
        "params": {
            "progress": progress,
            "total": total,
            "message": message
        }
    }


def create_log_notification(level: str, message: str, data: Optional[Dict] = None) -> Dict[str, Any]:
    """Create a logging notification."""
    params = {
        "level": level,
        "message": message
    }
    if data:
        params["data"] = data
    
    return {
        "jsonrpc": "2.0",
        "method": "notifications/message",
        "params": params
    }


def create_tools_list_changed_notification() -> Dict[str, Any]:
    """Create a notification that the tools list has changed."""
    return {
        "jsonrpc": "2.0",
        "method": "notifications/tools/list_changed"
    }


def create_resources_list_changed_notification() -> Dict[str, Any]:
    """Create a notification that the resources list has changed."""
    return {
        "jsonrpc": "2.0",
        "method": "notifications/resources/list_changed"
    }
