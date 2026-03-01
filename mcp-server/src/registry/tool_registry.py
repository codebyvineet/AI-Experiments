"""MongoDB-backed Tool Registry.

Stores tool metadata in MongoDB for dynamic registration and discovery.
For the POC, tools are seeded from code on startup.

Future enhancements:
- MCP Tool Search with BM25 + Vector hybrid search
- Deferred schema loading
- Tool versioning
"""
import logging
import os
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

# MongoDB settings
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://mongodb:27017")
DATABASE_NAME = os.getenv("MONGODB_DATABASE", "mcp_registry")


class ToolRegistry:
    """MongoDB-backed tool registry.
    
    Stores tool definitions in MongoDB for persistence and discoverability.
    Maintains in-memory cache of handlers for execution.
    """
    
    def __init__(self):
        self._client: Optional[AsyncIOMotorClient] = None
        self._db = None
        self._handlers: Dict[str, Callable] = {}
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize MongoDB connection."""
        if self._initialized:
            return
            
        logger.info(f"[Tool Registry] Connecting to MongoDB: {MONGODB_URL}")
        self._client = AsyncIOMotorClient(MONGODB_URL)
        self._db = self._client[DATABASE_NAME]
        
        # Create indexes
        await self._db.tools.create_index("name", unique=True)
        await self._db.tools.create_index("category")
        await self._db.tools.create_index("enabled")
        
        # Text index for BM25-style search (future)
        await self._db.tools.create_index([
            ("name", "text"),
            ("description", "text"),
            ("tags", "text")
        ])
        
        self._initialized = True
        logger.info("[Tool Registry] MongoDB connection established")
    
    async def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable,
        category: str = "general",
        tags: List[str] = None,
        permissions: List[str] = None,
        endpoint: str = None,
        http_method: str = "POST"
    ) -> None:
        """Register a tool in MongoDB and cache its handler.
        
        Args:
            name: Unique tool name
            description: Human-readable description
            input_schema: JSON Schema for input parameters
            handler: Async function that executes the tool
            category: Tool category (items, users, reports, etc.)
            tags: Searchable tags
            permissions: Required permissions
            endpoint: Backend API endpoint
            http_method: HTTP method for Backend API
        """
        await self.initialize()
        
        tool_doc = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "category": category,
            "tags": tags or [],
            "permissions": permissions or [],
            "endpoint": endpoint,
            "http_method": http_method,
            "enabled": True,
            "version": "1.0.0",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        
        # Upsert tool in MongoDB
        await self._db.tools.update_one(
            {"name": name},
            {"$set": tool_doc},
            upsert=True
        )
        
        # Cache handler in memory
        self._handlers[name] = handler
        
        logger.info(f"[Tool Registry] Registered tool: {name} (category: {category})")
    
    async def list_tools(self, enabled_only: bool = True) -> List[Dict[str, Any]]:
        """List all tools from MongoDB.
        
        Args:
            enabled_only: If True, only return enabled tools
            
        Returns:
            List of tool definitions (without handlers)
        """
        await self.initialize()
        
        query = {"enabled": True} if enabled_only else {}
        cursor = self._db.tools.find(query, {"_id": 0, "handler": 0})
        
        tools = []
        async for doc in cursor:
            # Convert to MCP format
            tools.append({
                "name": doc["name"],
                "description": doc["description"],
                "inputSchema": doc.get("inputSchema", {})
            })
        
        return tools
    
    async def get_tool(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a tool by name from MongoDB."""
        await self.initialize()
        return await self._db.tools.find_one({"name": name}, {"_id": 0})
    
    async def call_tool(self, name: str, arguments: Dict[str, Any], token: str) -> Any:
        """Execute a tool by name.
        
        Args:
            name: Tool name
            arguments: Tool arguments
            token: Authorization token
            
        Returns:
            Tool execution result
        """
        await self.initialize()
        
        if name not in self._handlers:
            logger.error(f"[Tool Registry] No handler for tool: {name}")
            raise ValueError(f"Unknown tool: {name}")
        
        handler = self._handlers[name]
        logger.info(f"[Tool Registry] Executing tool: {name}")
        
        import json
        result = await handler(arguments, token)
        
        if isinstance(result, dict):
            return json.dumps(result, indent=2, default=str)
        return result
    
    async def search_tools(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search tools using text search (BM25-style).
        
        NOTE: This is a basic implementation. For production with 100+ tools,
        implement hybrid BM25 + Vector search as documented in ARCHITECTURE.md.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of matching tools
        """
        await self.initialize()
        
        cursor = self._db.tools.find(
            {"$text": {"$search": query}, "enabled": True},
            {"score": {"$meta": "textScore"}, "_id": 0}
        ).sort([("score", {"$meta": "textScore"})]).limit(limit)
        
        results = []
        async for doc in cursor:
            results.append({
                "name": doc["name"],
                "description": doc["description"],
                "inputSchema": doc.get("inputSchema", {}),
                "score": doc.get("score", 0)
            })
        
        return results
    
    async def get_tools_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Get all tools in a category."""
        await self.initialize()
        
        cursor = self._db.tools.find(
            {"category": category, "enabled": True},
            {"_id": 0}
        )
        
        return await cursor.to_list(length=100)
    
    async def get_tool_count(self) -> int:
        """Get total number of registered tools."""
        await self.initialize()
        return await self._db.tools.count_documents({"enabled": True})
    
    async def disable_tool(self, name: str) -> bool:
        """Disable a tool (soft delete)."""
        await self.initialize()
        result = await self._db.tools.update_one(
            {"name": name},
            {"$set": {"enabled": False, "updated_at": datetime.now(timezone.utc)}}
        )
        return result.modified_count > 0
    
    async def enable_tool(self, name: str) -> bool:
        """Enable a tool."""
        await self.initialize()
        result = await self._db.tools.update_one(
            {"name": name},
            {"$set": {"enabled": True, "updated_at": datetime.now(timezone.utc)}}
        )
        return result.modified_count > 0
    
    def get_tools_description(self) -> str:
        """Get formatted description of all tools (from cache)."""
        descriptions = []
        for name, handler in self._handlers.items():
            descriptions.append(f"- {name}")
        return "\n".join(descriptions)


# Global instance
tool_registry = ToolRegistry()


# Legacy compatibility functions (used by existing tools)
async def register_tool(
    name: str,
    description: str,
    input_schema: Dict[str, Any],
    handler: Callable,
    **kwargs
) -> None:
    """Backwards-compatible register_tool function."""
    await tool_registry.register_tool(
        name=name,
        description=description,
        input_schema=input_schema,
        handler=handler,
        **kwargs
    )


async def list_all_tools() -> List[Dict[str, Any]]:
    """Backwards-compatible list_all_tools function."""
    return await tool_registry.list_tools()


async def call_tool(name: str, arguments: Dict[str, Any], token: str) -> Any:
    """Backwards-compatible call_tool function."""
    return await tool_registry.call_tool(name, arguments, token)
