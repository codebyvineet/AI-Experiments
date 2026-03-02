"""Dual Checkpointer for LangGraph: Redis (Hot) + MongoDB (Cold).

This implements a hot/cold storage pattern for LangGraph checkpoints:
- Hot storage (Redis): Fast access with TTL for active sessions
- Cold storage (MongoDB): Permanent storage for history and recovery

Benefits:
- Sub-millisecond reads from Redis for active sessions
- Automatic TTL expiration in Redis (saves memory)
- Full history preserved in MongoDB for audit/recovery
- Graceful degradation if Redis is unavailable
"""
import logging
from typing import Optional, Any, Iterator, Tuple, Sequence
from datetime import datetime

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)

logger = logging.getLogger(__name__)


class DualCheckpointer(BaseCheckpointSaver):
    """
    Dual storage checkpointer: Redis (hot) + MongoDB (cold).
    
    Write Strategy:
    - Write to both Redis AND MongoDB on every checkpoint
    - Redis has TTL for automatic expiration
    - MongoDB keeps permanent history
    
    Read Strategy:
    - Try Redis first (fast path)
    - Fall back to MongoDB if not in Redis (cold read)
    - Optionally warm up Redis cache on cold read
    
    Usage:
        ```python
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver
        from langgraph.checkpoint.mongodb.aio import AsyncMongoDBSaver
        
        redis_saver = AsyncRedisSaver(redis_client, ttl_config={"default_ttl": 30})
        mongo_saver = AsyncMongoDBSaver(mongo_client, db_name="checkpoints")
        
        dual = DualCheckpointer(hot=redis_saver, cold=mongo_saver)
        graph = builder.compile(checkpointer=dual)
        ```
    """
    
    def __init__(
        self,
        hot: BaseCheckpointSaver,
        cold: BaseCheckpointSaver,
        warm_cache_on_cold_read: bool = True
    ):
        """
        Initialize dual checkpointer.
        
        Args:
            hot: Redis checkpointer (fast, with TTL)
            cold: MongoDB checkpointer (permanent)
            warm_cache_on_cold_read: If True, populate hot cache when reading from cold
        """
        super().__init__()
        self.hot = hot
        self.cold = cold
        self.warm_cache = warm_cache_on_cold_read
        logger.info("DualCheckpointer initialized (Redis hot + MongoDB cold)")
    
    def get_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        """Get checkpoint - try hot first, fall back to cold."""
        # Try hot storage first
        try:
            result = self.hot.get_tuple(config)
            if result:
                logger.debug(f"[DualCheckpointer] Hot cache hit")
                return result
        except Exception as e:
            logger.warning(f"[DualCheckpointer] Hot storage error: {e}")
        
        # Fall back to cold storage
        try:
            result = self.cold.get_tuple(config)
            if result:
                logger.debug(f"[DualCheckpointer] Cold storage hit")
                # Warm up hot cache
                if self.warm_cache:
                    try:
                        self.hot.put(
                            config,
                            result.checkpoint,
                            result.metadata,
                            result.parent_config
                        )
                        logger.debug("[DualCheckpointer] Warmed hot cache")
                    except Exception as e:
                        logger.warning(f"[DualCheckpointer] Failed to warm cache: {e}")
                return result
        except Exception as e:
            logger.error(f"[DualCheckpointer] Cold storage error: {e}")
        
        return None
    
    def put(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> dict:
        """Write checkpoint to both hot and cold storage."""
        # Write to hot storage (Redis)
        try:
            hot_config = self.hot.put(config, checkpoint, metadata, new_versions)
            logger.debug("[DualCheckpointer] Written to hot storage")
        except Exception as e:
            logger.warning(f"[DualCheckpointer] Hot storage write failed: {e}")
            hot_config = config
        
        # Write to cold storage (MongoDB) - always attempt this
        try:
            cold_config = self.cold.put(config, checkpoint, metadata, new_versions)
            logger.debug("[DualCheckpointer] Written to cold storage")
        except Exception as e:
            logger.error(f"[DualCheckpointer] Cold storage write failed: {e}")
            cold_config = config
        
        return hot_config
    
    def put_writes(
        self,
        config: dict,
        writes: Sequence[Tuple[str, Any]],
        task_id: str
    ) -> None:
        """Write intermediate values to both storages."""
        # Write to hot
        try:
            self.hot.put_writes(config, writes, task_id)
        except Exception as e:
            logger.warning(f"[DualCheckpointer] Hot put_writes failed: {e}")
        
        # Write to cold
        try:
            self.cold.put_writes(config, writes, task_id)
        except Exception as e:
            logger.error(f"[DualCheckpointer] Cold put_writes failed: {e}")
    
    def list(
        self,
        config: Optional[dict],
        *,
        filter: Optional[dict] = None,
        before: Optional[dict] = None,
        limit: Optional[int] = None
    ) -> Iterator[CheckpointTuple]:
        """List checkpoints - use cold storage for complete history."""
        # Always use cold storage for listing (has full history)
        try:
            yield from self.cold.list(config, filter=filter, before=before, limit=limit)
        except Exception as e:
            logger.error(f"[DualCheckpointer] List failed: {e}")
            # Try hot as fallback
            try:
                yield from self.hot.list(config, filter=filter, before=before, limit=limit)
            except Exception as e2:
                logger.error(f"[DualCheckpointer] Hot list also failed: {e2}")


class AsyncDualCheckpointer(BaseCheckpointSaver):
    """
    Async version of DualCheckpointer for use with LangGraph async graphs.
    
    This wraps AsyncRedisSaver and AsyncMongoDBSaver for the hot/cold pattern.
    """
    
    def __init__(
        self,
        hot: "AsyncRedisSaver",
        cold: "AsyncMongoDBSaver",
        warm_cache_on_cold_read: bool = True
    ):
        """
        Initialize async dual checkpointer.
        
        Args:
            hot: AsyncRedisSaver instance
            cold: AsyncMongoDBSaver instance
            warm_cache_on_cold_read: If True, populate hot cache when reading from cold
        """
        super().__init__()
        self.hot = hot
        self.cold = cold
        self.warm_cache = warm_cache_on_cold_read
        logger.info("AsyncDualCheckpointer initialized")
    
    async def aget_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        """Get checkpoint asynchronously - try hot first, fall back to cold."""
        # Try hot storage first
        try:
            result = await self.hot.aget_tuple(config)
            if result:
                logger.debug("[AsyncDualCheckpointer] Hot cache hit")
                return result
        except Exception as e:
            logger.warning(f"[AsyncDualCheckpointer] Hot storage error: {e}")
        
        # Fall back to cold storage
        try:
            result = await self.cold.aget_tuple(config)
            if result:
                logger.debug("[AsyncDualCheckpointer] Cold storage hit")
                # Warm up hot cache
                if self.warm_cache:
                    try:
                        await self.hot.aput(
                            config,
                            result.checkpoint,
                            result.metadata,
                            {}  # new_versions not needed for cache warming
                        )
                        logger.debug("[AsyncDualCheckpointer] Warmed hot cache")
                    except Exception as e:
                        logger.warning(f"[AsyncDualCheckpointer] Failed to warm cache: {e}")
                return result
        except Exception as e:
            logger.error(f"[AsyncDualCheckpointer] Cold storage error: {e}")
        
        return None
    
    async def aput(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> dict:
        """Write checkpoint to both hot and cold storage asynchronously."""
        import asyncio
        
        # Write to both in parallel for speed
        hot_task = asyncio.create_task(
            self._safe_hot_put(config, checkpoint, metadata, new_versions)
        )
        cold_task = asyncio.create_task(
            self._safe_cold_put(config, checkpoint, metadata, new_versions)
        )
        
        results = await asyncio.gather(hot_task, cold_task, return_exceptions=True)
        
        # Return config from hot (or cold if hot failed)
        if not isinstance(results[0], Exception):
            return results[0]
        elif not isinstance(results[1], Exception):
            return results[1]
        else:
            logger.error(f"[AsyncDualCheckpointer] Both writes failed!")
            return config
    
    async def _safe_hot_put(self, config, checkpoint, metadata, new_versions):
        """Safe wrapper for hot storage put."""
        try:
            return await self.hot.aput(config, checkpoint, metadata, new_versions)
        except Exception as e:
            logger.warning(f"[AsyncDualCheckpointer] Hot write failed: {e}")
            raise
    
    async def _safe_cold_put(self, config, checkpoint, metadata, new_versions):
        """Safe wrapper for cold storage put."""
        try:
            return await self.cold.aput(config, checkpoint, metadata, new_versions)
        except Exception as e:
            logger.error(f"[AsyncDualCheckpointer] Cold write failed: {e}")
            raise
    
    async def aput_writes(
        self,
        config: dict,
        writes: Sequence[Tuple[str, Any]],
        task_id: str
    ) -> None:
        """Write intermediate values to both storages asynchronously."""
        import asyncio
        
        async def safe_hot():
            try:
                await self.hot.aput_writes(config, writes, task_id)
            except Exception as e:
                logger.warning(f"[AsyncDualCheckpointer] Hot put_writes failed: {e}")
        
        async def safe_cold():
            try:
                await self.cold.aput_writes(config, writes, task_id)
            except Exception as e:
                logger.error(f"[AsyncDualCheckpointer] Cold put_writes failed: {e}")
        
        await asyncio.gather(safe_hot(), safe_cold())
    
    async def alist(
        self,
        config: Optional[dict],
        *,
        filter: Optional[dict] = None,
        before: Optional[dict] = None,
        limit: Optional[int] = None
    ):
        """List checkpoints asynchronously - use cold storage for complete history."""
        try:
            async for item in self.cold.alist(config, filter=filter, before=before, limit=limit):
                yield item
        except Exception as e:
            logger.error(f"[AsyncDualCheckpointer] List failed: {e}")
    
    # Sync methods delegate to async
    def get_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self.aget_tuple(config))
    
    def put(self, config, checkpoint, metadata, new_versions) -> dict:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.aput(config, checkpoint, metadata, new_versions)
        )


async def create_dual_checkpointer(
    redis_url: str,
    mongo_url: str,
    mongo_db_name: str = "checkpoints",
    redis_ttl_minutes: int = 30,
    refresh_on_read: bool = True
) -> AsyncDualCheckpointer:
    """
    Factory function to create a configured AsyncDualCheckpointer.
    
    Args:
        redis_url: Redis connection URL (e.g., "redis://localhost:6379")
        mongo_url: MongoDB connection URL
        mongo_db_name: Database name for MongoDB checkpoints
        redis_ttl_minutes: TTL for Redis entries in minutes
        refresh_on_read: Whether to refresh TTL when reading from Redis
        
    Returns:
        Configured AsyncDualCheckpointer instance
    """
    from redis.asyncio import Redis
    from motor.motor_asyncio import AsyncIOMotorClient
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver
    from langgraph.checkpoint.mongodb.aio import AsyncMongoDBSaver
    
    logger.info(f"Creating dual checkpointer: Redis TTL={redis_ttl_minutes}min")
    
    # Create Redis saver (hot storage)
    redis_client = Redis.from_url(redis_url)
    hot = AsyncRedisSaver(
        connection=redis_client,
        ttl_config={
            "default_ttl": redis_ttl_minutes,
            "refresh_on_read": refresh_on_read
        }
    )
    await hot.setup()
    
    # Create MongoDB saver (cold storage)
    mongo_client = AsyncIOMotorClient(mongo_url)
    cold = AsyncMongoDBSaver(mongo_client, db_name=mongo_db_name)
    
    return AsyncDualCheckpointer(hot=hot, cold=cold)
