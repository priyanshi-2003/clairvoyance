"""
Hybrid Configuration Provider

Orchestrates between different providers based on variable classification and frequency.
Implements the core logic of the hybrid configuration resolution engine.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from ...redis.client import get_redis_service
from ...redis.refresh_worker import get_refresh_worker
from ..models import (
    CacheStats,
    ConfigResolutionResult,
    ConfigVariable,
    FrequencyClass,
    VariableClassification,
)
from .base import BaseConfigProvider
from .devcycle import DevCycleProvider
from .environment import EnvironmentProvider


class HybridProvider(BaseConfigProvider):
    """
    Hybrid provider that implements the configuration resolution strategy:

    1. Core variables → Environment only
    2. Non-core variables → Frequency-based routing:
       - High frequency: Redis cache + background refresh from DevCycle
       - Medium frequency: Redis cache with longer TTL
       - Low frequency: Direct DevCycle API calls
    3. Fallback chain: DevCycle → Environment → Default
    """

    def __init__(
        self,
        environment_provider: EnvironmentProvider,
        devcycle_provider: DevCycleProvider,
    ):
        super().__init__("hybrid")
        self.environment_provider = environment_provider
        self.devcycle_provider = devcycle_provider
        self._cache_stats = CacheStats()
        self._redis_service = None
        self._refresh_worker = None
        self._cache_namespace = "config"

    async def _get_redis_service(self):
        """Get Redis service instance"""
        if self._redis_service is None:
            self._redis_service = await get_redis_service()
        return self._redis_service

    async def _get_refresh_worker(self):
        """Get Redis refresh worker instance"""
        if self._refresh_worker is None:
            self._refresh_worker = await get_refresh_worker()
        return self._refresh_worker

    async def get_value(self, variable: ConfigVariable) -> ConfigResolutionResult:
        """Get configuration value using hybrid strategy"""
        start_time = time.time()
        self._cache_stats.total_requests += 1

        try:
            # Step 1: Check if this is a core variable
            if variable.classification == VariableClassification.CORE:
                logger.debug(f"Core variable {variable.key} - using environment only")
                result = await self.environment_provider.get_value(variable)
                result.resolution_time_ms = (time.time() - start_time) * 1000
                return result

            # Step 2: Non-core variable - apply frequency-based strategy
            return await self._resolve_non_core_variable(variable, start_time)

        except Exception as e:
            self._cache_stats.errors += 1
            logger.error(f"Hybrid provider error for {variable.key}: {e}")

            # Fallback to environment
            try:
                result = await self.environment_provider.get_value(variable)
                result.source = "hybrid_fallback_env"
                result.resolution_time_ms = (time.time() - start_time) * 1000
                return result
            except Exception as fallback_error:
                logger.error(f"Fallback error for {variable.key}: {fallback_error}")
                return ConfigResolutionResult(
                    key=variable.key,
                    value=variable.default_value,
                    source="hybrid_error",
                    value_type=variable.value_type,
                    resolution_time_ms=(time.time() - start_time) * 1000,
                    error=str(e),
                )

    async def _resolve_non_core_variable(
        self, variable: ConfigVariable, start_time: float
    ) -> ConfigResolutionResult:
        """Resolve non-core variable based on frequency class"""

        if variable.frequency_class == FrequencyClass.LOW:
            # Low frequency: Direct DevCycle API call
            return await self._resolve_low_frequency(variable, start_time)

        elif variable.frequency_class in [FrequencyClass.HIGH, FrequencyClass.MEDIUM]:
            # High/Medium frequency: Check cache first
            return await self._resolve_cached_variable(variable, start_time)

        else:
            # Unknown frequency class - default to low frequency
            logger.warning(
                f"Unknown frequency class for {variable.key}, using low frequency"
            )
            return await self._resolve_low_frequency(variable, start_time)

    async def _resolve_low_frequency(
        self, variable: ConfigVariable, start_time: float
    ) -> ConfigResolutionResult:
        """Resolve low-frequency variable with direct API call"""
        logger.debug(f"Low frequency variable {variable.key} - direct DevCycle API")

        # Try DevCycle first
        devcycle_result = await self.devcycle_provider.get_value(variable)

        if devcycle_result.success and devcycle_result.value is not None:
            self._cache_stats.api_calls += 1
            devcycle_result.source = "devcycle_direct"
            devcycle_result.resolution_time_ms = (time.time() - start_time) * 1000
            return devcycle_result

        # Fallback to environment
        logger.debug(f"DevCycle failed for {variable.key}, falling back to environment")
        env_result = await self.environment_provider.get_value(variable)
        env_result.source = "environment_fallback"
        env_result.resolution_time_ms = (time.time() - start_time) * 1000
        return env_result

    async def _resolve_cached_variable(
        self, variable: ConfigVariable, start_time: float
    ) -> ConfigResolutionResult:
        """Resolve high/medium frequency variable with caching"""
        redis_service = await self._get_redis_service()
        cache_key = f"{variable.key}"

        # Check cache first
        try:
            cached_value = await redis_service.get(cache_key, self._cache_namespace)

            if cached_value is not None:
                logger.debug(f"Cache hit for {variable.key}")
                self._cache_stats.cache_hits += 1

                # Convert cached value
                result = self._convert_and_validate_value(cached_value, variable)
                result.source = "cache"
                result.cached = True
                result.cache_hit = True
                result.resolution_time_ms = (time.time() - start_time) * 1000
                return result

            else:
                logger.debug(f"Cache miss for {variable.key}")
                self._cache_stats.cache_misses += 1

        except Exception as cache_error:
            logger.error(f"Cache error for {variable.key}: {cache_error}")

        # Cache miss - get from DevCycle and cache the result
        return await self._fetch_and_cache_variable(variable, start_time)

    async def _fetch_and_cache_variable(
        self, variable: ConfigVariable, start_time: float
    ) -> ConfigResolutionResult:
        """Fetch variable from DevCycle and cache the result"""
        redis_service = await self._get_redis_service()
        cache_key = f"{variable.key}"

        # Try DevCycle
        devcycle_result = await self.devcycle_provider.get_value(variable)

        if devcycle_result.success and devcycle_result.value is not None:
            # Cache the successful result
            try:
                cache_value = str(devcycle_result.value)
                await redis_service.set(
                    cache_key,
                    cache_value,
                    ttl=variable.cache_ttl,
                    namespace=self._cache_namespace,
                )
                logger.debug(f"Cached {variable.key} with TTL {variable.cache_ttl}s")

                # Register for background refresh if high frequency
                if variable.frequency_class == FrequencyClass.HIGH:
                    await self._register_background_refresh(variable)

            except Exception as cache_error:
                logger.error(f"Failed to cache {variable.key}: {cache_error}")

            self._cache_stats.api_calls += 1
            devcycle_result.source = "devcycle_fresh"
            devcycle_result.cached = True
            devcycle_result.cache_hit = False
            devcycle_result.resolution_time_ms = (time.time() - start_time) * 1000
            return devcycle_result

        # DevCycle failed - try environment fallback
        logger.debug(f"DevCycle failed for {variable.key}, trying environment fallback")
        env_result = await self.environment_provider.get_value(variable)

        if env_result.success and env_result.value is not None:
            # Cache environment fallback with shorter TTL
            try:
                cache_value = str(env_result.value)
                fallback_ttl = min(variable.cache_ttl, 60)  # Max 1 minute for fallback
                await redis_service.set(
                    cache_key,
                    cache_value,
                    ttl=fallback_ttl,
                    namespace=self._cache_namespace,
                )
                logger.debug(f"Cached environment fallback for {variable.key}")
            except Exception as cache_error:
                logger.error(
                    f"Failed to cache environment fallback for {variable.key}: {cache_error}"
                )

        env_result.source = "environment_fallback"
        env_result.cached = True
        env_result.cache_hit = False
        env_result.resolution_time_ms = (time.time() - start_time) * 1000
        return env_result

    async def _register_background_refresh(self, variable: ConfigVariable):
        """Register variable for background refresh"""
        if variable.refresh_interval <= 0:
            return

        try:
            refresh_worker = await self._get_refresh_worker()

            # Create refresh callback
            async def refresh_callback():
                """Callback to refresh variable from DevCycle"""
                try:
                    result = await self.devcycle_provider.get_value(variable)
                    if result.success and result.value is not None:
                        logger.debug(
                            f"Background refresh successful for {variable.key}"
                        )
                        return str(result.value)
                    else:
                        logger.warning(
                            f"Background refresh failed for {variable.key}: {result.error}"
                        )
                        return None
                except Exception as e:
                    logger.error(f"Background refresh error for {variable.key}: {e}")
                    return None

            # Register with refresh worker
            refresh_worker.register_key(
                key=variable.key,
                namespace=self._cache_namespace,
                refresh_interval=variable.refresh_interval,
                ttl=variable.cache_ttl,
                refresh_callback=refresh_callback,
                enabled=True,
            )

            logger.debug(f"Registered background refresh for {variable.key}")

        except Exception as e:
            logger.error(
                f"Failed to register background refresh for {variable.key}: {e}"
            )

    async def health_check(self) -> bool:
        """Check health of all providers"""
        try:
            env_healthy = await self.environment_provider.health_check()
            devcycle_healthy = await self.devcycle_provider.health_check()

            # Redis health check
            redis_healthy = True
            try:
                redis_service = await self._get_redis_service()
                health_result = await redis_service.health_check()
                redis_healthy = health_result.get("status") == "healthy"
            except Exception as e:
                logger.error(f"Redis health check failed: {e}")
                redis_healthy = False

            return env_healthy and (devcycle_healthy or redis_healthy)

        except Exception as e:
            logger.error(f"Hybrid provider health check failed: {e}")
            return False

    async def invalidate_cache(self, key: str) -> bool:
        """Invalidate cached value for a specific key"""
        try:
            redis_service = await self._get_redis_service()
            result = await redis_service.delete(key, self._cache_namespace)
            logger.info(f"Invalidated cache for {key}: {result}")
            return result
        except Exception as e:
            logger.error(f"Failed to invalidate cache for {key}: {e}")
            return False

    async def warm_cache(self, variables: List[ConfigVariable]) -> Dict[str, bool]:
        """Pre-warm cache for multiple variables"""
        results = {}

        for variable in variables:
            if variable.classification == VariableClassification.CORE:
                continue  # Skip core variables

            try:
                await self._fetch_and_cache_variable(variable, time.time())
                results[variable.key] = True
                logger.debug(f"Cache warmed for {variable.key}")
            except Exception as e:
                logger.error(f"Failed to warm cache for {variable.key}: {e}")
                results[variable.key] = False

        return results

    def get_cache_stats(self) -> CacheStats:
        """Get cache performance statistics"""
        if self._cache_stats.total_requests > 0:
            self._cache_stats.avg_resolution_time_ms = (
                self._cache_stats.avg_resolution_time_ms
                * (self._cache_stats.total_requests - 1)
                + 0  # This would need to be tracked per request
            ) / self._cache_stats.total_requests

        return self._cache_stats

    def get_stats(self) -> dict:
        """Get comprehensive provider statistics"""
        base_stats = super().get_stats()
        base_stats.update(
            {
                "cache_stats": {
                    "total_requests": self._cache_stats.total_requests,
                    "cache_hits": self._cache_stats.cache_hits,
                    "cache_misses": self._cache_stats.cache_misses,
                    "hit_rate": self._cache_stats.hit_rate,
                    "api_calls": self._cache_stats.api_calls,
                    "errors": self._cache_stats.errors,
                    "error_rate": self._cache_stats.error_rate,
                },
                "providers": {
                    "environment": self.environment_provider.get_stats(),
                    "devcycle": self.devcycle_provider.get_stats(),
                },
            }
        )
        return base_stats

    async def close(self):
        """Close all provider connections"""
        try:
            await self.devcycle_provider.close()
            logger.debug("Hybrid provider closed")
        except Exception as e:
            logger.error(f"Error closing hybrid provider: {e}")
