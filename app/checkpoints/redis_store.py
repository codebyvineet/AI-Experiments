"""Redis cold state checkpoint storage."""

import json
from typing import Optional, Dict, Any, List
from datetime import datetime
import redis.asyncio as redis

from app.config import get_settings
from app.models import AgentState

settings = get_settings()


class RedisCheckpoint:
    """Redis checkpoint manager for cold state storage."""
    
    def __init__(self):
        self.client: Optional[redis.Redis] = None
        self.checkpoint_prefix = "checkpoint:"
        self.cold_checkpoint_prefix = "cold_checkpoint:"
    
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
    
    async def save_cold_checkpoint(self, state: AgentState, ttl_seconds: int = 86400) -> str:
        """Save agent state as cold checkpoint (Redis storage)."""
        state_dict = state.model_dump(mode="json")
        state_dict["state_type"] = "cold"
        state_dict["updated_at"] = datetime.utcnow().isoformat()
        
        key = f"{self.cold_checkpoint_prefix}{state.session_id}"
        await self.client.setex(
            key,
            ttl_seconds,
            json.dumps(state_dict)
        )
        return key
    
    async def get_cold_checkpoint(self, session_id: str) -> Optional[AgentState]:
        """Get cold checkpoint by session ID."""
        key = f"{self.cold_checkpoint_prefix}{session_id}"
        data = await self.client.get(key)
        if data:
            state_dict = json.loads(data)
            return AgentState(**state_dict)
        return None
    
    async def delete_cold_checkpoint(self, session_id: str) -> bool:
        """Delete cold checkpoint."""
        key = f"{self.cold_checkpoint_prefix}{session_id}"
        result = await self.client.delete(key)
        return result > 0
    
    async def migrate_to_cold(self, state: AgentState, ttl_seconds: int = 86400) -> str:
        """Migrate a hot checkpoint to cold storage."""
        state.state_type = "cold"
        return await self.save_cold_checkpoint(state, ttl_seconds)
    
    async def list_cold_checkpoints(self, pattern: str = "*") -> List[str]:
        """List all cold checkpoint keys matching pattern."""
        keys = []
        async for key in self.client.scan_iter(
            match=f"{self.cold_checkpoint_prefix}{pattern}"
        ):
            keys.append(key.replace(self.cold_checkpoint_prefix, ""))
        return keys
    
    # Token blacklist management for RBAC
    async def blacklist_token(self, token: str, ttl_seconds: int = 3600) -> None:
        """Add token to blacklist."""
        await self.client.setex(f"blacklist:{token}", ttl_seconds, "1")
    
    async def is_token_blacklisted(self, token: str) -> bool:
        """Check if token is blacklisted."""
        return await self.client.exists(f"blacklist:{token}") > 0
    
    # Session management
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


# Global instance
redis_checkpoint = RedisCheckpoint()


async def get_redis() -> redis.Redis:
    """Get Redis client instance."""
    return redis_checkpoint.client
