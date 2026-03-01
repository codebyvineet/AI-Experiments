"""MCP Server implementation with RBAC support."""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import json

from app.auth import authorization_tool, decode_token, ROLE_PERMISSIONS
from app.models import UserRole, MCPRequest, MCPResponse, ItemCreate, ItemUpdate
from app.crud.operations import item_crud, user_crud
from app.config.logging_config import get_logger, LogContext

logger = get_logger("mcp_server")


class MCPServer:
    """
    MCP (Model Context Protocol) Server implementation.
    
    Provides tools and resources for AI agents with RBAC support.
    """
    
    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.resources: Dict[str, Dict[str, Any]] = {}
        self._register_default_tools()
        self._register_default_resources()
    
    def _register_default_tools(self):
        """Register default MCP tools."""
        self.tools = {
            "create_item": {
                "name": "create_item",
                "description": "Create a new item in the system",
                "required_permission": "items:write",
                "parameters": {
                    "name": {"type": "string", "required": True},
                    "description": {"type": "string", "required": False},
                    "data": {"type": "object", "required": False}
                }
            },
            "read_item": {
                "name": "read_item",
                "description": "Read an item from the system by ID",
                "required_permission": "items:read",
                "parameters": {
                    "item_id": {"type": "string", "required": True}
                }
            },
            "list_items": {
                "name": "list_items",
                "description": "List all items in the system",
                "required_permission": "items:read",
                "parameters": {}
            },
            "update_item": {
                "name": "update_item",
                "description": "Update an existing item",
                "required_permission": "items:write",
                "parameters": {
                    "item_id": {"type": "string", "required": True},
                    "updates": {"type": "object", "required": True}
                }
            },
            "delete_item": {
                "name": "delete_item",
                "description": "Delete an item from the system",
                "required_permission": "items:delete",
                "parameters": {
                    "item_id": {"type": "string", "required": True}
                }
            },
            "execute_agent": {
                "name": "execute_agent",
                "description": "Execute an AI agent task",
                "required_permission": "agent:execute",
                "parameters": {
                    "session_id": {"type": "string", "required": True},
                    "action": {"type": "string", "required": True}
                }
            },
            "manage_users": {
                "name": "manage_users",
                "description": "Manage system users (admin only)",
                "required_permission": "users:write",
                "parameters": {
                    "action": {"type": "string", "required": True},
                    "user_data": {"type": "object", "required": False}
                }
            }
        }
    
    def _register_default_resources(self):
        """Register default MCP resources."""
        self.resources = {
            "items": {
                "name": "items",
                "description": "Collection of items in the system",
                "uri": "mcp://items",
                "required_permission": "items:read"
            },
            "users": {
                "name": "users",
                "description": "User management resource",
                "uri": "mcp://users",
                "required_permission": "users:read"
            },
            "agent_sessions": {
                "name": "agent_sessions",
                "description": "AI agent sessions",
                "uri": "mcp://agent/sessions",
                "required_permission": "agent:execute"
            }
        }
    
    def validate_access(self, token: str, required_permission: str) -> Dict[str, Any]:
        """Validate token and check for required permission."""
        try:
            token_data = decode_token(token)
            permissions = token_data.permissions or []
            
            if required_permission not in permissions:
                return {
                    "authorized": False,
                    "error": f"Permission denied: requires '{required_permission}'",
                    "user_permissions": permissions
                }
            
            return {
                "authorized": True,
                "user_id": token_data.user_id,
                "username": token_data.username,
                "role": token_data.role.value if token_data.role else None,
                "permissions": permissions
            }
        except Exception as e:
            return {
                "authorized": False,
                "error": str(e)
            }
    
    def list_tools(self, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """List available tools, filtered by user permissions."""
        if not token:
            # Return all tools without permission info
            return [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"]
                }
                for tool in self.tools.values()
            ]
        
        # Filter tools based on user permissions
        try:
            token_data = decode_token(token)
            permissions = token_data.permissions or []
            
            available_tools = []
            for tool in self.tools.values():
                if tool["required_permission"] in permissions:
                    available_tools.append({
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["parameters"],
                        "accessible": True
                    })
                else:
                    available_tools.append({
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["parameters"],
                        "accessible": False
                    })
            
            return available_tools
        except Exception:
            return list(self.tools.values())
    
    def list_resources(self, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """List available resources, filtered by user permissions."""
        if not token:
            return [
                {
                    "name": res["name"],
                    "description": res["description"],
                    "uri": res["uri"]
                }
                for res in self.resources.values()
            ]
        
        try:
            token_data = decode_token(token)
            permissions = token_data.permissions or []
            
            available_resources = []
            for res in self.resources.values():
                if res["required_permission"] in permissions:
                    available_resources.append({
                        "name": res["name"],
                        "description": res["description"],
                        "uri": res["uri"],
                        "accessible": True
                    })
                else:
                    available_resources.append({
                        "name": res["name"],
                        "description": res["description"],
                        "uri": res["uri"],
                        "accessible": False
                    })
            
            return available_resources
        except Exception:
            return [
                {
                    "name": res["name"],
                    "description": res["description"],
                    "uri": res["uri"]
                }
                for res in self.resources.values()
            ]
    
    async def call_tool(
        self,
        token: str,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> MCPResponse:
        """Call a tool with RBAC validation and actual execution."""
        log = LogContext(logger, agent_type="mcp", phase="tool_execution")
        
        tool = self.tools.get(tool_name)
        if not tool:
            log.error(f"Tool not found: {tool_name}")
            return MCPResponse(error={
                "code": "tool_not_found",
                "message": f"Tool '{tool_name}' not found"
            })
        
        # Validate access
        access = self.validate_access(token, tool["required_permission"])
        if not access["authorized"]:
            log.error(f"Unauthorized access to {tool_name}: {access.get('error')}")
            return MCPResponse(error={
                "code": "unauthorized",
                "message": access["error"]
            })
        
        # Validate required parameters
        for param_name, param_info in tool["parameters"].items():
            if param_info.get("required") and param_name not in arguments:
                log.error(f"Missing required parameter: {param_name}")
                return MCPResponse(error={
                    "code": "invalid_arguments",
                    "message": f"Missing required parameter: {param_name}"
                })
        
        log.info(f"🔧 Executing MCP tool: {tool_name}", data={"arguments": arguments, "user": access.get("username")})
        
        # Actually execute the tool
        try:
            result = await self._execute_tool(tool_name, arguments, access)
            log.info(f"✅ MCP tool {tool_name} completed", data={"result": result})
            return MCPResponse(result=result)
        except Exception as e:
            log.error(f"❌ MCP tool {tool_name} failed: {str(e)}")
            return MCPResponse(error={
                "code": "execution_error",
                "message": str(e)
            })
    
    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        access: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute the actual tool operation."""
        user_id = access.get("user_id", "unknown")
        username = access.get("username", "unknown")
        
        if tool_name == "create_item":
            # Create item in database
            item_data = ItemCreate(
                name=arguments.get("name"),
                description=arguments.get("description", ""),
                data=arguments.get("data", {})
            )
            item = await item_crud.create_item(item_data, user_id)
            return {
                "tool": tool_name,
                "status": "success",
                "item_id": item.id,
                "item": {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description,
                    "data": item.data,
                    "created_at": item.created_at.isoformat() if item.created_at else None
                },
                "executed_by": username,
                "executed_at": datetime.now(timezone.utc).isoformat()
            }
        
        elif tool_name == "read_item":
            # Read item from database
            item_id = arguments.get("item_id")
            item = await item_crud.get_item(item_id)
            if not item:
                raise ValueError(f"Item not found: {item_id}")
            return {
                "tool": tool_name,
                "status": "success",
                "item": {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description,
                    "data": item.data,
                    "owner_id": item.owner_id,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "updated_at": item.updated_at.isoformat() if item.updated_at else None
                },
                "executed_by": username,
                "executed_at": datetime.now(timezone.utc).isoformat()
            }
        
        elif tool_name == "update_item":
            # Update item in database
            item_id = arguments.get("item_id")
            updates = arguments.get("updates", {})
            item_update = ItemUpdate(**updates)
            item = await item_crud.update_item(item_id, item_update, user_id)
            if not item:
                raise ValueError(f"Item not found or not owned by user: {item_id}")
            return {
                "tool": tool_name,
                "status": "success",
                "item_id": item.id,
                "item": {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description,
                    "data": item.data,
                    "updated_at": item.updated_at.isoformat() if item.updated_at else None
                },
                "executed_by": username,
                "executed_at": datetime.now(timezone.utc).isoformat()
            }
        
        elif tool_name == "delete_item":
            # Delete item from database
            item_id = arguments.get("item_id")
            deleted = await item_crud.delete_item(item_id, user_id)
            if not deleted:
                raise ValueError(f"Item not found or not owned by user: {item_id}")
            return {
                "tool": tool_name,
                "status": "success",
                "item_id": item_id,
                "deleted": True,
                "executed_by": username,
                "executed_at": datetime.now(timezone.utc).isoformat()
            }
        
        elif tool_name == "list_items":
            # List all items
            items = await item_crud.list_items()
            return {
                "tool": tool_name,
                "status": "success",
                "items": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "description": item.description,
                        "data": item.data
                    }
                    for item in items
                ],
                "count": len(items),
                "executed_by": username,
                "executed_at": datetime.now(timezone.utc).isoformat()
            }
        
        elif tool_name == "execute_agent":
            # Agent execution - return acknowledgment (actual execution handled elsewhere)
            return {
                "tool": tool_name,
                "status": "success",
                "session_id": arguments.get("session_id"),
                "action": arguments.get("action"),
                "message": "Agent execution requested",
                "executed_by": username,
                "executed_at": datetime.now(timezone.utc).isoformat()
            }
        
        elif tool_name == "manage_users":
            # User management (admin only)
            action = arguments.get("action")
            user_data = arguments.get("user_data", {})
            
            if action == "list":
                users = await user_crud.list_users()
                return {
                    "tool": tool_name,
                    "status": "success",
                    "action": action,
                    "users": [
                        {"id": u.id, "username": u.username, "role": u.role, "email": u.email}
                        for u in users
                    ],
                    "executed_by": username,
                    "executed_at": datetime.now(timezone.utc).isoformat()
                }
            else:
                return {
                    "tool": tool_name,
                    "status": "success",
                    "action": action,
                    "message": f"User management action '{action}' acknowledged",
                    "executed_by": username,
                    "executed_at": datetime.now(timezone.utc).isoformat()
                }
        
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
    
    async def read_resource(
        self,
        token: str,
        resource_uri: str
    ) -> MCPResponse:
        """Read a resource with RBAC validation."""
        # Find resource by URI
        resource = None
        for res in self.resources.values():
            if res["uri"] == resource_uri:
                resource = res
                break
        
        if not resource:
            return MCPResponse(error={
                "code": "resource_not_found",
                "message": f"Resource '{resource_uri}' not found"
            })
        
        # Validate access
        access = self.validate_access(token, resource["required_permission"])
        if not access["authorized"]:
            return MCPResponse(error={
                "code": "unauthorized",
                "message": access["error"]
            })
        
        return MCPResponse(result={
            "resource": resource["name"],
            "uri": resource_uri,
            "accessed_by": access["username"],
            "accessed_at": datetime.now(timezone.utc).isoformat()
        })
    
    def handle_request(self, request: MCPRequest, token: str) -> MCPResponse:
        """Handle an MCP request."""
        method = request.method
        params = request.params
        
        if method == "tools/list":
            return MCPResponse(result={
                "tools": self.list_tools(token)
            })
        
        elif method == "resources/list":
            return MCPResponse(result={
                "resources": self.list_resources(token)
            })
        
        elif method == "initialize":
            return MCPResponse(result={
                "protocolVersion": "1.0",
                "capabilities": {
                    "tools": True,
                    "resources": True,
                    "prompts": False
                },
                "serverInfo": {
                    "name": "MCP Demo Server",
                    "version": "1.0.0"
                }
            })
        
        else:
            return MCPResponse(error={
                "code": "method_not_found",
                "message": f"Method '{method}' not supported"
            })


# Global instance
mcp_server = MCPServer()
