"""
Redis Client Service

Simple Redis client for direct key-value operations with TTL support.
Provides basic get/set operations and automatic TTL refresh functionality.
"""

import asyncio
import json
from typing import Any, Dict, List, Optional

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config.redis import RedisConfig, get_redis_client


class RedisService:
    """Simple Redis service for key-value operations"""

    def __init__(self):
        self.config = RedisConfig()
        self._client: Optional[Redis] = None

    async def get_client(self) -> Redis:
        """Get Redis client instance"""
        if self._client is None:
            self._client = await get_redis_client()
        return self._client

    def _format_key(self, key: str, namespace: str = "default") -> str:
        """Format key with namespace and environment"""
        return f"{self.config.namespace_prefix}:{self.config.environment}:{namespace}:{key}"

    async def get(self, key: str, namespace: str = "default") -> Optional[str]:
        """Get value from Redis"""
        try:
            client = await self.get_client()
            formatted_key = self._format_key(key, namespace)
            value = await client.get(formatted_key)

            if value:
                logger.debug(f"Redis GET hit: {formatted_key}")
                return value
            else:
                logger.debug(f"Redis GET miss: {formatted_key}")
                return None

        except RedisError as e:
            logger.error(f"Redis GET error for key {key}: {e}")
            return None

    async def set(
        self,
        key: str,
        value: str,
        ttl: Optional[int] = None,
        namespace: str = "default",
    ) -> bool:
        """Set value in Redis with optional TTL"""
        try:
            client = await self.get_client()
            formatted_key = self._format_key(key, namespace)

            if ttl is None:
                ttl = self.config.default_ttl

            result = await client.set(formatted_key, value, ex=ttl)

            if result:
                logger.debug(f"Redis SET success: {formatted_key} (TTL: {ttl}s)")
            else:
                logger.warning(f"Redis SET failed: {formatted_key}")

            return bool(result)

        except RedisError as e:
            logger.error(f"Redis SET error for key {key}: {e}")
            return False

    async def get_json(self, key: str, namespace: str = "default") -> Optional[Dict]:
        """Get JSON value from Redis"""
        try:
            value = await self.get(key, namespace)
            if value:
                return json.loads(value)
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for key {key}: {e}")
            return None

    async def set_json(
        self,
        key: str,
        value: Dict,
        ttl: Optional[int] = None,
        namespace: str = "default",
    ) -> bool:
        """Set JSON value in Redis"""
        try:
            json_str = json.dumps(value)
            return await self.set(key, json_str, ttl, namespace)
        except (TypeError, ValueError) as e:
            logger.error(f"JSON encode error for key {key}: {e}")
            return False

    async def delete(self, key: str, namespace: str = "default") -> bool:
        """Delete key from Redis"""
        try:
            client = await self.get_client()
            formatted_key = self._format_key(key, namespace)
            result = await client.delete(formatted_key)

            if result:
                logger.debug(f"Redis DELETE success: {formatted_key}")
            else:
                logger.debug(f"Redis DELETE miss: {formatted_key}")

            return bool(result)

        except RedisError as e:
            logger.error(f"Redis DELETE error for key {key}: {e}")
            return False

    async def exists(self, key: str, namespace: str = "default") -> bool:
        """Check if key exists in Redis"""
        try:
            client = await self.get_client()
            formatted_key = self._format_key(key, namespace)
            result = await client.exists(formatted_key)
            return bool(result)
        except RedisError as e:
            logger.error(f"Redis EXISTS error for key {key}: {e}")
            return False

    async def get_ttl(self, key: str, namespace: str = "default") -> int:
        """Get TTL for key (-1 if no TTL, -2 if key doesn't exist)"""
        try:
            client = await self.get_client()
            formatted_key = self._format_key(key, namespace)
            return await client.ttl(formatted_key)
        except RedisError as e:
            logger.error(f"Redis TTL error for key {key}: {e}")
            return -2

    async def extend_ttl(self, key: str, ttl: int, namespace: str = "default") -> bool:
        """Extend TTL for existing key"""
        try:
            client = await self.get_client()
            formatted_key = self._format_key(key, namespace)
            result = await client.expire(formatted_key, ttl)

            if result:
                logger.debug(f"Redis TTL extended: {formatted_key} (TTL: {ttl}s)")
            else:
                logger.warning(f"Redis TTL extend failed: {formatted_key}")

            return bool(result)

        except RedisError as e:
            logger.error(f"Redis EXPIRE error for key {key}: {e}")
            return False

    async def get_keys_by_pattern(
        self, pattern: str, namespace: str = "default"
    ) -> List[str]:
        """Get keys matching pattern"""
        try:
            client = await self.get_client()
            formatted_pattern = self._format_key(pattern, namespace)
            keys = await client.keys(formatted_pattern)

            # Remove namespace prefix from returned keys
            prefix = (
                f"{self.config.namespace_prefix}:{self.config.environment}:{namespace}:"
            )
            return [key.replace(prefix, "") for key in keys]

        except RedisError as e:
            logger.error(f"Redis KEYS error for pattern {pattern}: {e}")
            return []

    async def health_check(self) -> Dict[str, Any]:
        """Perform Redis health check"""
        try:
            client = await self.get_client()
            start_time = asyncio.get_event_loop().time()
            await client.ping()
            latency = (asyncio.get_event_loop().time() - start_time) * 1000

            info = await client.info()

            return {
                "status": "healthy",
                "latency_ms": round(latency, 2),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "redis_version": info.get("redis_version", "unknown"),
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}


# Global Redis service instance
_redis_service: Optional[RedisService] = None


async def get_redis_service() -> RedisService:
    """Get global Redis service instance"""
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service


# Convenience functions for direct usage
async def redis_get(key: str, namespace: str = "default") -> Optional[str]:
    """Get value from Redis"""
    service = await get_redis_service()
    return await service.get(key, namespace)


async def redis_set(
    key: str, value: str, ttl: Optional[int] = None, namespace: str = "default"
) -> bool:
    """Set value in Redis"""
    service = await get_redis_service()
    return await service.set(key, value, ttl, namespace)


async def redis_get_json(key: str, namespace: str = "default") -> Optional[Dict]:
    """Get JSON value from Redis"""
    service = await get_redis_service()
    return await service.get_json(key, namespace)


async def redis_set_json(
    key: str, value: Dict, ttl: Optional[int] = None, namespace: str = "default"
) -> bool:
    """Set JSON value in Redis"""
    service = await get_redis_service()
    return await service.set_json(key, value, ttl, namespace)


async def redis_delete(key: str, namespace: str = "default") -> bool:
    """Delete key from Redis"""
    service = await get_redis_service()
    return await service.delete(key, namespace)


async def redis_exists(key: str, namespace: str = "default") -> bool:
    """Check if key exists in Redis"""
    service = await get_redis_service()
    return await service.exists(key, namespace)
