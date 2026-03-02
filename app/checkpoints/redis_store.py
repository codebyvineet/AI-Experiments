"""Redis connection management and utilities.

This module provides:
- Redis connection for the application
- Token blacklist for authentication
- Session cache for user sessions

Agent checkpointing is handled by LangGraph (see app/agent/checkpointer.py).
"""

import json
from typing import Optional, Dict, Any, List
import redis.asyncio as redis

from app.config import get_settings

settings = get_settings()


class RedisConnection:
    """Redis connection manager with auth utilities."""
    
    def __init__(self):
        self.client: Optional[redis.Redis] = None
    
    async def connect(self):
        """Connect to Redis."""
        self.client = redis.from_url(
            settings.redis_url,
            db=settings.redis_db,
            decode_responses=True
        )
    
    async def disconnect(self):
        """Disconnect from Redis."""
        if self.client:
            await self.client.close()
    
    # =========================================================================
    # Token Blacklist (for auth/logout)
    # =========================================================================
    
    async def blacklist_token(self, token: str, ttl_seconds: int = 3600) -> None:
        """Add token to blacklist."""
        await self.client.setex(f"blacklist:{token}", ttl_seconds, "1")
    
    async def is_token_blacklisted(self, token: str) -> bool:
        """Check if token is blacklisted."""
        return await self.client.exists(f"blacklist:{token}") > 0
    
    # =========================================================================
    # Session Cache (for user sessions)
    # =========================================================================
    
    async def set_user_session(self, user_id: str, session_data: Dict[str, Any], ttl_seconds: int = 3600):
        """Set user session data."""
        key = f"session:{user_id}"
        await self.client.setex(key, ttl_seconds, json.dumps(session_data))
    
    async def get_user_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user session data."""
        key = f"session:{user_id}"
        data = await self.client.get(key)
        if data:
            return json.loads(data)
        return None
    
    async def delete_user_session(self, user_id: str) -> bool:
        """Delete user session."""
        key = f"session:{user_id}"
        result = await self.client.delete(key)
        return result > 0


# Global instance - provides Redis connection and auth utilities
# Note: Agent checkpointing uses LangGraph's AsyncRedisSaver
redis_checkpoint = RedisConnection()


async def get_redis() -> redis.Redis:
    """Get Redis client instance."""
    return redis_checkpoint.client
