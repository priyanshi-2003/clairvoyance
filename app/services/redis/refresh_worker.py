"""
Redis TTL Refresh Worker

Background worker that automatically refreshes Redis keys with configurable TTL intervals.
Supports scalable key refresh patterns for feature flags and other cached data.
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config.redis import RedisConfig, get_redis_client


@dataclass
class RefreshConfig:
    """Configuration for key refresh"""

    key: str
    namespace: str
    refresh_interval: int  # seconds
    ttl: int  # seconds
    refresh_callback: Callable[[], Any]  # Function to get fresh value
    enabled: bool = True


class RedisRefreshWorker:
    """Background worker for refreshing Redis keys"""

    def __init__(self):
        self.config = RedisConfig()
        self._client: Optional[Redis] = None
        self._refresh_configs: Dict[str, RefreshConfig] = {}
        self._worker_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._lock_prefix = "refresh_lock"

    async def get_client(self) -> Redis:
        """Get Redis client instance"""
        if self._client is None:
            self._client = await get_redis_client()
        return self._client

    def _format_key(self, key: str, namespace: str) -> str:
        """Format key with namespace and environment"""
        return f"{self.config.namespace_prefix}:{self.config.environment}:{namespace}:{key}"

    def _format_lock_key(self, key: str, namespace: str) -> str:
        """Format lock key for distributed locking"""
        return f"{self.config.namespace_prefix}:{self.config.environment}:{self._lock_prefix}:{namespace}:{key}"

    async def _acquire_lock(self, key: str, namespace: str, lock_ttl: int = 60) -> bool:
        """Acquire distributed lock for key refresh"""
        try:
            client = await self.get_client()
            lock_key = self._format_lock_key(key, namespace)

            # Use SET NX EX for atomic lock acquisition
            result = await client.set(lock_key, "1", nx=True, ex=lock_ttl)

            if result:
                logger.debug(f"Acquired refresh lock: {lock_key}")
            else:
                logger.debug(f"Failed to acquire refresh lock: {lock_key}")

            return bool(result)

        except RedisError as e:
            logger.error(f"Lock acquisition error for {key}: {e}")
            return False

    async def _release_lock(self, key: str, namespace: str) -> bool:
        """Release distributed lock"""
        try:
            client = await self.get_client()
            lock_key = self._format_lock_key(key, namespace)
            result = await client.delete(lock_key)

            if result:
                logger.debug(f"Released refresh lock: {lock_key}")
            else:
                logger.debug(f"Lock already released: {lock_key}")

            return bool(result)

        except RedisError as e:
            logger.error(f"Lock release error for {key}: {e}")
            return False

    def register_key(
        self,
        key: str,
        namespace: str,
        refresh_interval: int,
        ttl: int,
        refresh_callback: Callable[[], Any],
        enabled: bool = True,
    ) -> None:
        """Register a key for automatic refresh"""
        config_id = f"{namespace}:{key}"

        refresh_config = RefreshConfig(
            key=key,
            namespace=namespace,
            refresh_interval=refresh_interval,
            ttl=ttl,
            refresh_callback=refresh_callback,
            enabled=enabled,
        )

        self._refresh_configs[config_id] = refresh_config
        logger.info(
            f"Registered key for refresh: {config_id} (interval: {refresh_interval}s, TTL: {ttl}s)"
        )

    def register_keys(self, configs: List[Dict[str, Any]]) -> None:
        """Register multiple keys for automatic refresh"""
        for config in configs:
            self.register_key(
                key=config["key"],
                namespace=config["namespace"],
                refresh_interval=config.get(
                    "refresh_interval", self.config.refresh_interval
                ),
                ttl=config.get("ttl", self.config.default_ttl),
                refresh_callback=config["refresh_callback"],
                enabled=config.get("enabled", True),
            )

        logger.info(f"Bulk registered {len(configs)} keys for refresh")

    def unregister_key(self, key: str, namespace: str) -> None:
        """Unregister a key from automatic refresh"""
        config_id = f"{namespace}:{key}"
        if config_id in self._refresh_configs:
            del self._refresh_configs[config_id]
            logger.info(f"Unregistered key from refresh: {config_id}")

    def enable_key_refresh(self, key: str, namespace: str) -> None:
        """Enable refresh for a specific key"""
        config_id = f"{namespace}:{key}"
        if config_id in self._refresh_configs:
            self._refresh_configs[config_id].enabled = True
            logger.info(f"Enabled refresh for key: {config_id}")

    def disable_key_refresh(self, key: str, namespace: str) -> None:
        """Disable refresh for a specific key"""
        config_id = f"{namespace}:{key}"
        if config_id in self._refresh_configs:
            self._refresh_configs[config_id].enabled = False
            logger.info(f"Disabled refresh for key: {config_id}")

    async def _refresh_key(self, config: RefreshConfig) -> bool:
        """Refresh a single key"""
        try:
            # Acquire lock to prevent multiple instances from refreshing the same key
            lock_acquired = await self._acquire_lock(
                config.key, config.namespace, config.refresh_interval + 10
            )

            if not lock_acquired:
                logger.debug(
                    f"Skipping refresh for {config.namespace}:{config.key} - lock held by another instance"
                )
                return False

            try:
                # Call the refresh callback to get fresh value
                fresh_value = (
                    await config.refresh_callback()
                    if asyncio.iscoroutinefunction(config.refresh_callback)
                    else config.refresh_callback()
                )

                if fresh_value is not None:
                    # Store the fresh value in Redis
                    client = await self.get_client()
                    formatted_key = self._format_key(config.key, config.namespace)

                    # Convert to JSON if it's a dict/list, otherwise use string
                    if isinstance(fresh_value, (dict, list)):
                        value_str = json.dumps(fresh_value)
                    else:
                        value_str = str(fresh_value)

                    result = await client.set(formatted_key, value_str, ex=config.ttl)

                    if result:
                        logger.info(
                            f"Refreshed key: {config.namespace}:{config.key} (TTL: {config.ttl}s)"
                        )
                        return True
                    else:
                        logger.error(
                            f"Failed to set refreshed value for {config.namespace}:{config.key}"
                        )
                        return False
                else:
                    logger.warning(
                        f"Refresh callback returned None for {config.namespace}:{config.key}"
                    )
                    return False

            finally:
                # Always release the lock
                await self._release_lock(config.key, config.namespace)

        except Exception as e:
            logger.error(f"Error refreshing key {config.namespace}:{config.key}: {e}")
            return False

    async def _worker_loop(self) -> None:
        """Main worker loop"""
        logger.info("Redis refresh worker started")

        while not self._stop_event.is_set():
            try:
                # Process all registered keys
                refresh_tasks = []

                for config_id, config in self._refresh_configs.items():
                    if not config.enabled:
                        continue

                    # Check if key needs refresh based on TTL
                    try:
                        client = await self.get_client()
                        formatted_key = self._format_key(config.key, config.namespace)
                        current_ttl = await client.ttl(formatted_key)

                        # Refresh if key doesn't exist (-2) or TTL is less than half the refresh interval
                        refresh_threshold = config.refresh_interval // 2

                        if current_ttl == -2 or (
                            current_ttl > 0 and current_ttl <= refresh_threshold
                        ):
                            logger.debug(
                                f"Key {config_id} needs refresh (TTL: {current_ttl}s)"
                            )
                            refresh_tasks.append(self._refresh_key(config))
                        else:
                            logger.debug(
                                f"Key {config_id} still fresh (TTL: {current_ttl}s)"
                            )

                    except RedisError as e:
                        logger.error(f"Error checking TTL for {config_id}: {e}")

                # Execute refresh tasks concurrently
                if refresh_tasks:
                    results = await asyncio.gather(
                        *refresh_tasks, return_exceptions=True
                    )
                    success_count = sum(1 for r in results if r is True)
                    logger.debug(
                        f"Refresh cycle completed: {success_count}/{len(refresh_tasks)} successful"
                    )

                # Wait before next cycle
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=30
                    )  # Check every 30 seconds
                except asyncio.TimeoutError:
                    continue  # Normal timeout, continue loop

            except Exception as e:
                logger.error(f"Error in refresh worker loop: {e}")
                await asyncio.sleep(10)  # Wait before retrying

        logger.info("Redis refresh worker stopped")

    async def start(self) -> None:
        """Start the refresh worker"""
        if self._worker_task is None or self._worker_task.done():
            self._stop_event.clear()
            self._worker_task = asyncio.create_task(self._worker_loop())
            logger.info("Redis refresh worker task created")

    async def stop(self) -> None:
        """Stop the refresh worker"""
        if self._worker_task and not self._worker_task.done():
            self._stop_event.set()
            try:
                await asyncio.wait_for(self._worker_task, timeout=10)
            except asyncio.TimeoutError:
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass
            logger.info("Redis refresh worker stopped")

    def get_status(self) -> Dict[str, Any]:
        """Get worker status"""
        return {
            "running": self._worker_task is not None and not self._worker_task.done(),
            "registered_keys": len(self._refresh_configs),
            "enabled_keys": sum(
                1 for config in self._refresh_configs.values() if config.enabled
            ),
            "configs": {
                config_id: {
                    "key": config.key,
                    "namespace": config.namespace,
                    "refresh_interval": config.refresh_interval,
                    "ttl": config.ttl,
                    "enabled": config.enabled,
                }
                for config_id, config in self._refresh_configs.items()
            },
        }


# Global refresh worker instance
_refresh_worker: Optional[RedisRefreshWorker] = None


async def get_refresh_worker() -> RedisRefreshWorker:
    """Get global refresh worker instance"""
    global _refresh_worker
    if _refresh_worker is None:
        _refresh_worker = RedisRefreshWorker()
    return _refresh_worker


# Convenience functions
async def register_refresh_key(
    key: str,
    namespace: str,
    refresh_interval: int,
    ttl: int,
    refresh_callback: Callable[[], Any],
    enabled: bool = True,
) -> None:
    """Register a key for automatic refresh"""
    worker = await get_refresh_worker()
    worker.register_key(
        key, namespace, refresh_interval, ttl, refresh_callback, enabled
    )


async def register_refresh_keys(configs: List[Dict[str, Any]]) -> None:
    """Register multiple keys for automatic refresh"""
    worker = await get_refresh_worker()
    worker.register_keys(configs)


async def start_refresh_worker() -> None:
    """Start the refresh worker"""
    worker = await get_refresh_worker()
    await worker.start()


async def stop_refresh_worker() -> None:
    """Stop the refresh worker"""
    worker = await get_refresh_worker()
    await worker.stop()
