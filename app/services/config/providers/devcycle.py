"""
DevCycle Configuration Provider

Provider for accessing configuration values from DevCycle API.
Supports REST API integration with service token authentication.
"""

import asyncio
import json
import time
from typing import Any, Dict, Optional

import aiohttp
from loguru import logger

from ..models import ConfigResolutionResult, ConfigVariable, DevCycleConfig
from .base import BaseConfigProvider


class DevCycleProvider(BaseConfigProvider):
    """Provider for DevCycle feature flags and configuration"""

    def __init__(self, config: DevCycleConfig):
        super().__init__("devcycle")
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None

        # Override circuit breaker settings from config
        self._circuit_breaker_threshold = config.circuit_breaker_threshold
        self._circuit_breaker_timeout = config.circuit_breaker_timeout

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
            headers = {
                "Authorization": f"Bearer {self.config.service_token}",
                "Content-Type": "application/json",
                "User-Agent": "Clairvoyance/1.0",
            }
            self._session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self._session

    async def get_value(self, variable: ConfigVariable) -> ConfigResolutionResult:
        """Get value from DevCycle API"""
        start_time = time.time()

        if not self.config.enabled:
            return ConfigResolutionResult(
                key=variable.key,
                value=None,
                source="devcycle_disabled",
                value_type=variable.value_type,
                resolution_time_ms=(time.time() - start_time) * 1000,
                error="DevCycle provider disabled",
            )

        if not self.config.service_token:
            return ConfigResolutionResult(
                key=variable.key,
                value=None,
                source="devcycle_no_token",
                value_type=variable.value_type,
                resolution_time_ms=(time.time() - start_time) * 1000,
                error="DevCycle service token not configured",
            )

        try:
            session = await self._get_session()

            # Use DevCycle Variables API
            url = f"{self.config.api_endpoint}/v1/variables/{variable.devcycle_key}"

            # Add user context as query parameters
            params = {}
            if self.config.user_context:
                for key, value in self.config.user_context.items():
                    params[f"user_{key}"] = str(value)

            logger.debug(f"DevCycle API request: {url} with params: {params}")

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    raw_value = data.get("value")

                    logger.debug(f"DevCycle response for {variable.key}: {raw_value}")

                    # Convert and validate
                    result = self._convert_and_validate_value(raw_value, variable)
                    result.resolution_time_ms = (time.time() - start_time) * 1000

                    return result

                elif response.status == 404:
                    # Variable not found in DevCycle
                    logger.debug(f"DevCycle variable {variable.devcycle_key} not found")
                    return ConfigResolutionResult(
                        key=variable.key,
                        value=None,
                        source="devcycle_not_found",
                        value_type=variable.value_type,
                        resolution_time_ms=(time.time() - start_time) * 1000,
                        error="Variable not found in DevCycle",
                    )

                else:
                    # API error
                    error_text = await response.text()
                    logger.error(f"DevCycle API error {response.status}: {error_text}")
                    return ConfigResolutionResult(
                        key=variable.key,
                        value=None,
                        source="devcycle_api_error",
                        value_type=variable.value_type,
                        resolution_time_ms=(time.time() - start_time) * 1000,
                        error=f"API error {response.status}: {error_text}",
                    )

        except asyncio.TimeoutError:
            logger.error(f"DevCycle API timeout for {variable.key}")
            return ConfigResolutionResult(
                key=variable.key,
                value=None,
                source="devcycle_timeout",
                value_type=variable.value_type,
                resolution_time_ms=(time.time() - start_time) * 1000,
                error="API request timeout",
            )

        except Exception as e:
            logger.error(f"DevCycle provider error for {variable.key}: {e}")
            return ConfigResolutionResult(
                key=variable.key,
                value=None,
                source="devcycle_error",
                value_type=variable.value_type,
                resolution_time_ms=(time.time() - start_time) * 1000,
                error=str(e),
            )

    async def get_all_variables(self) -> Dict[str, Any]:
        """Get all variables from DevCycle (for debugging/monitoring)"""
        if not self.config.enabled or not self.config.service_token:
            return {}

        try:
            session = await self._get_session()
            url = f"{self.config.api_endpoint}/v1/variables"

            params = {}
            if self.config.user_context:
                for key, value in self.config.user_context.items():
                    params[f"user_{key}"] = str(value)

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("variables", {})
                else:
                    logger.error(f"DevCycle get all variables error: {response.status}")
                    return {}

        except Exception as e:
            logger.error(f"DevCycle get all variables error: {e}")
            return {}

    async def health_check(self) -> bool:
        """Check DevCycle API health"""
        if not self.config.enabled or not self.config.service_token:
            return False

        try:
            session = await self._get_session()

            # Use a simple health check endpoint or try to get variables
            url = f"{self.config.api_endpoint}/v1/variables"

            async with session.get(url) as response:
                return response.status in [200, 404]  # 404 is OK (no variables)

        except Exception as e:
            logger.error(f"DevCycle health check failed: {e}")
            return False

    async def close(self):
        """Close HTTP session"""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("DevCycle session closed")

    def update_user_context(self, user_context: Dict[str, Any]):
        """Update user context for DevCycle requests"""
        self.config.user_context.update(user_context)
        logger.debug(f"Updated DevCycle user context: {user_context}")

    def get_stats(self) -> dict:
        """Get provider statistics"""
        base_stats = super().get_stats()
        base_stats.update(
            {
                "enabled": self.config.enabled,
                "has_token": bool(self.config.service_token),
                "api_endpoint": self.config.api_endpoint,
                "user_context": self.config.user_context,
                "session_open": self._session is not None and not self._session.closed,
            }
        )
        return base_stats
