"""JSON-RPC 2.0 protocol implementation for MCP."""
import uuid
import logging
from typing import Any, Dict, Optional, Union
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 Request."""
    jsonrpc: str = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[Union[str, int]] = None  # None for notifications


class JSONRPCResponse(BaseModel):
    """JSON-RPC 2.0 Response."""
    jsonrpc: str = "2.0"
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    id: Optional[Union[str, int]] = None


class JSONRPCError:
    """Standard JSON-RPC 2.0 error codes."""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    
    # Custom MCP errors
    UNAUTHORIZED = -32001
    FORBIDDEN = -32002
    NOT_FOUND = -32003
    TOOL_EXECUTION_ERROR = -32004


def create_response(request_id: Optional[Union[str, int]], result: Any) -> Dict[str, Any]:
    """Create a successful JSON-RPC response."""
    return {
        "jsonrpc": "2.0",
        "result": result,
        "id": request_id
    }


def create_error_response(
    request_id: Optional[Union[str, int]], 
    code: int, 
    message: str,
    data: Optional[Any] = None
) -> Dict[str, Any]:
    """Create an error JSON-RPC response."""
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {
        "jsonrpc": "2.0",
        "error": error,
        "id": request_id
    }


def create_notification(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a JSON-RPC notification (no id, no response expected)."""
    notification = {
        "jsonrpc": "2.0",
        "method": method
    }
    if params:
        notification["params"] = params
    return notification


def parse_request(data: Dict[str, Any]) -> JSONRPCRequest:
    """Parse and validate a JSON-RPC request."""
    logger.debug(f"[JSONRPC] Parsing request: {data}")
    
    if "jsonrpc" not in data or data["jsonrpc"] != "2.0":
        raise ValueError("Invalid JSON-RPC version")
    
    if "method" not in data:
        raise ValueError("Missing method")
    
    return JSONRPCRequest(
        jsonrpc=data.get("jsonrpc", "2.0"),
        method=data["method"],
        params=data.get("params"),
        id=data.get("id")
    )


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())
