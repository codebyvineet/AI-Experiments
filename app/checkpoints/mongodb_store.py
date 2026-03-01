"""MongoDB hot state checkpoint storage."""

from typing import Optional, Dict, Any, List
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from bson import ObjectId

from app.config import get_settings
from app.models import AgentState

settings = get_settings()


class MongoDBCheckpoint:
    """MongoDB checkpoint manager for hot state storage."""
    
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
    
    async def connect(self):
        """Connect to MongoDB."""
        self.client = AsyncIOMotorClient(settings.mongodb_url)
        self.db = self.client[settings.mongodb_database]
        
        # Create indexes
        await self.db.checkpoints.create_index("session_id", unique=True)
        await self.db.checkpoints.create_index("user_id")
        await self.db.users.create_index("username", unique=True)
        await self.db.users.create_index("email", unique=True)
        await self.db.items.create_index("owner_id")
    
    async def disconnect(self):
        """Disconnect from MongoDB."""
        if self.client:
            self.client.close()
    
    async def save_checkpoint(self, state: AgentState) -> str:
        """Save agent state checkpoint (hot storage)."""
        state_dict = state.model_dump(exclude={"id"})
        state_dict["updated_at"] = datetime.utcnow()
        
        result = await self.db.checkpoints.update_one(
            {"session_id": state.session_id},
            {"$set": state_dict},
            upsert=True
        )
        
        if result.upserted_id:
            return str(result.upserted_id)
        
        doc = await self.db.checkpoints.find_one({"session_id": state.session_id})
        return str(doc["_id"]) if doc else ""
    
    async def get_checkpoint(self, session_id: str) -> Optional[AgentState]:
        """Get agent state checkpoint by session ID."""
        doc = await self.db.checkpoints.find_one({"session_id": session_id})
        if doc:
            doc["id"] = str(doc.pop("_id"))
            return AgentState(**doc)
        return None
    
    async def delete_checkpoint(self, session_id: str) -> bool:
        """Delete agent state checkpoint."""
        result = await self.db.checkpoints.delete_one({"session_id": session_id})
        return result.deleted_count > 0
    
    async def list_checkpoints(self, user_id: str) -> List[AgentState]:
        """List all checkpoints for a user."""
        cursor = self.db.checkpoints.find({"user_id": user_id})
        checkpoints = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            checkpoints.append(AgentState(**doc))
        return checkpoints


# Global instance
mongodb_checkpoint = MongoDBCheckpoint()


async def get_mongodb() -> AsyncIOMotorDatabase:
    """Get MongoDB database instance."""
    return mongodb_checkpoint.db
