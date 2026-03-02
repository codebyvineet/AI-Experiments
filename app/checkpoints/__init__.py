"""Database connection management.

This module provides MongoDB and Redis connections for the application.

For agent checkpointing, use LangGraph's checkpointers:
- app/agent/checkpointer.py: AsyncDualCheckpointer (Redis hot + MongoDB cold)
- langgraph-checkpoint-mongodb: AsyncMongoDBSaver
- langgraph-checkpoint-redis: AsyncRedisSaver
"""

from app.checkpoints.mongodb_store import mongodb_checkpoint, get_mongodb, MongoDBConnection
from app.checkpoints.redis_store import redis_checkpoint, get_redis, RedisConnection

__all__ = [
    "mongodb_checkpoint",
    "get_mongodb",
    "MongoDBConnection",
    "redis_checkpoint",
    "get_redis",
    "RedisConnection",
]
