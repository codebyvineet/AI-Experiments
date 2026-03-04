"""MongoDB database connection management.

This module provides the MongoDB connection for the application.
Agent checkpointing uses LangGraph MongoDBSaver (see app/agent/graph.py).
"""

from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings

settings = get_settings()


class MongoDBConnection:
    """MongoDB connection manager."""
    
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
    
    async def connect(self):
        """Connect to MongoDB."""
        self.client = AsyncIOMotorClient(settings.mongodb_url)
        self.db = self.client[settings.mongodb_database]
        
        # Create indexes for application data
        await self.db.users.create_index("username", unique=True)
        await self.db.users.create_index("email", unique=True)
        await self.db.items.create_index("owner_id")
    
    async def disconnect(self):
        """Disconnect from MongoDB."""
        if self.client:
            self.client.close()


# Global instance - provides database connection
# Note: Agent checkpointing uses LangGraph's AsyncMongoDBSaver
mongodb_checkpoint = MongoDBConnection()


async def get_mongodb() -> AsyncIOMotorDatabase:
    """Get MongoDB database instance."""
    return mongodb_checkpoint.db
