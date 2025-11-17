"""
Redis Cluster Configuration and Connection Factory

This module provides Redis cluster connection management for the Clairvoyance voice agent platform.
It supports both single-node and cluster configurations with proper error handling and observability.
"""

import asyncio
import os
from typing import Any, Dict, List, Optional

from loguru import logger
from redis.asyncio import Redis
from redis.asyncio.cluster import RedisCluster
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError


class RedisConfig:
    """Redis configuration management"""

    def __init__(self):
        # Simple Redis configuration - only essential variables
        self.redis_host = os.getenv("REDIS_HOST", "")
        self.redis_port = os.getenv("REDIS_PORT", "")
        self.password = os.getenv("REDIS_PASSWORD", None)

        # Optional cluster configuration (for advanced users)
        self.cluster_nodes = os.getenv("REDIS_CLUSTER_NODES", "")

        # Fixed connection settings (no need for env vars)
        self.use_tls = False
        self.pool_size = 10
        self.max_connections = 50
        self.socket_timeout = 5.0
        self.socket_connect_timeout = 5.0

        # Simplified cache configuration with smart defaults
        self.default_ttl = int(os.getenv("REDIS_CACHE_TTL", "300"))  # 5 minutes
        self.namespace_prefix = os.getenv("REDIS_CACHE_NAMESPACE", "clairvoyance")
        self.enable_refresh = os.getenv("REDIS_CACHE_REFRESH", "true").lower() == "true"

        # Environment and service identification
        self.environment = os.getenv("ENVIRONMENT", "production")

        # Smart defaults calculated from base TTL
        self.high_freq_ttl = max(
            self.default_ttl // 10, 10
        )  # TTL/10, minimum 10 seconds
        self.refresh_interval = max(self.default_ttl // 10, 10)  # Same as high_freq_ttl
        self.refresh_lock_ttl = max(
            self.refresh_interval - 5, 5
        )  # 5 seconds less than interval, minimum 5

    def is_redis_configured(self) -> bool:
        """Check if Redis is properly configured"""
        # Primary check: REDIS_HOST and REDIS_PORT
        if self.redis_host.strip() and self.redis_port.strip():
            try:
                int(self.redis_port)  # Validate port is a number
                return True
            except ValueError:
                return False

        # Optional: Check if cluster nodes are configured
        if self.cluster_nodes.strip():
            return True

        return False

    def get_startup_nodes(self) -> List[Dict[str, Any]]:
        """Get Redis nodes configuration"""
        startup_nodes = []

        # Primary approach: Use REDIS_HOST and REDIS_PORT
        if self.redis_host.strip() and self.redis_port.strip():
            try:
                port = int(self.redis_port)
                startup_nodes.append({"host": self.redis_host, "port": port})
                logger.info(f"Using Redis single node: {self.redis_host}:{port}")
            except ValueError:
                logger.error(f"Invalid Redis port: {self.redis_port}")

        # Optional: Parse cluster nodes if provided
        elif self.cluster_nodes.strip():
            for hostport in self.cluster_nodes.split(","):
                hostport = hostport.strip()
                if not hostport:
                    continue
                try:
                    host, port = hostport.split(":")
                    startup_nodes.append(
                        {"host": host.strip(), "port": int(port.strip())}
                    )
                except ValueError:
                    logger.error(f"Invalid Redis cluster node format: {hostport}")
                    continue

            if startup_nodes:
                logger.info(f"Using Redis cluster with {len(startup_nodes)} nodes")

        if not startup_nodes:
            raise ValueError(
                "No valid Redis configuration found. Please set REDIS_HOST and REDIS_PORT."
            )

        return startup_nodes


class RedisClusterFactory:
    """Factory for creating Redis cluster connections"""

    def __init__(self, config: Optional[RedisConfig] = None):
        self.config = config or RedisConfig()
        self._cluster_client: Optional[RedisCluster] = None
        self._single_client: Optional[Redis] = None

    async def get_cluster_client(self) -> RedisCluster:
        """Get or create Redis cluster client"""
        if self._cluster_client is None:
            await self._create_cluster_client()
        return self._cluster_client

    async def get_single_client(self) -> Redis:
        """Get or create single Redis client (for development/testing)"""
        if self._single_client is None:
            await self._create_single_client()
        return self._single_client

    async def _create_cluster_client(self) -> None:
        """Create Redis cluster client"""
        try:
            startup_nodes = self.config.get_startup_nodes()

            # If only one node, use single client
            if len(startup_nodes) == 1:
                logger.info(
                    "Single Redis node detected, using Redis client instead of cluster"
                )
                await self._create_single_client()
                return

            logger.info(
                f"Creating Redis cluster client with {len(startup_nodes)} nodes"
            )

            self._cluster_client = RedisCluster(
                startup_nodes=startup_nodes,
                password=self.config.password,
                ssl=self.config.use_tls,
                decode_responses=True,
                socket_timeout=self.config.socket_timeout,
                socket_connect_timeout=self.config.socket_connect_timeout,
                max_connections=self.config.max_connections,
                retry_on_timeout=True,
                health_check_interval=30,
                skip_full_coverage_check=True,  # Allow partial cluster for development
            )

            # Test connection
            await self._cluster_client.ping()
            logger.info("Redis cluster connection established successfully")

        except Exception as e:
            logger.error(f"Failed to create Redis cluster client: {e}")
            # Fallback to single client if cluster fails
            logger.info("Falling back to single Redis client")
            await self._create_single_client()

    async def _create_single_client(self) -> None:
        """Create single Redis client"""
        try:
            startup_nodes = self.config.get_startup_nodes()
            node = startup_nodes[0]

            logger.info(f"Creating single Redis client: {node['host']}:{node['port']}")

            self._single_client = Redis(
                host=node["host"],
                port=node["port"],
                password=self.config.password,
                ssl=self.config.use_tls,
                decode_responses=True,
                socket_timeout=self.config.socket_timeout,
                socket_connect_timeout=self.config.socket_connect_timeout,
                max_connections=self.config.pool_size,
                retry_on_timeout=True,
                health_check_interval=30,
            )

            # Test connection
            await self._single_client.ping()
            logger.info("Single Redis connection established successfully")

        except Exception as e:
            logger.error(f"Failed to create Redis client: {e}")
            raise RedisConnectionError(f"Cannot connect to Redis: {e}")

    async def get_client(self) -> Redis:
        """Get appropriate Redis client (cluster or single)"""
        if self._cluster_client is not None:
            return self._cluster_client
        elif self._single_client is not None:
            return self._single_client
        else:
            # Try cluster first, fallback to single
            try:
                await self.get_cluster_client()
                return self._cluster_client or self._single_client
            except Exception:
                await self.get_single_client()
                return self._single_client

    async def close(self) -> None:
        """Close all Redis connections"""
        if self._cluster_client:
            await self._cluster_client.aclose()
            self._cluster_client = None

        if self._single_client:
            await self._single_client.aclose()
            self._single_client = None

        logger.info("Redis connections closed")

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on Redis connections"""
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
                "cluster_enabled": isinstance(client, RedisCluster),
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}


# Global Redis factory instance
_redis_factory: Optional[RedisClusterFactory] = None


async def get_redis_factory() -> RedisClusterFactory:
    """Get global Redis factory instance"""
    global _redis_factory
    if _redis_factory is None:
        _redis_factory = RedisClusterFactory()
    return _redis_factory


async def get_redis_client() -> Redis:
    """Get Redis client instance"""
    factory = await get_redis_factory()
    return await factory.get_client()


async def close_redis_connections():
    """Close all Redis connections"""
    global _redis_factory
    if _redis_factory:
        await _redis_factory.close()
        _redis_factory = None
