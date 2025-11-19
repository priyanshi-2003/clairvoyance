"""
Environment Configuration Provider

Provider for accessing environment variables directly.
Used for core variables that should not use external services.
"""

import os
import time
from typing import Optional

from loguru import logger

from ..models import ConfigResolutionResult, ConfigVariable
from .base import BaseConfigProvider


class EnvironmentProvider(BaseConfigProvider):
    """Provider for environment variables"""

    def __init__(self):
        super().__init__("environment")

    async def get_value(self, variable: ConfigVariable) -> ConfigResolutionResult:
        """Get value from environment variables"""
        start_time = time.time()

        try:
            # Get raw value from environment
            raw_value = os.environ.get(variable.key)

            logger.debug(
                f"Environment lookup for {variable.key}: {'found' if raw_value else 'not found'}"
            )

            # Convert and validate
            result = self._convert_and_validate_value(raw_value, variable)
            result.resolution_time_ms = (time.time() - start_time) * 1000

            return result

        except Exception as e:
            logger.error(f"Environment provider error for {variable.key}: {e}")
            return ConfigResolutionResult(
                key=variable.key,
                value=variable.default_value,
                source="environment_error",
                value_type=variable.value_type,
                resolution_time_ms=(time.time() - start_time) * 1000,
                error=str(e),
            )

    async def health_check(self) -> bool:
        """Environment provider is always healthy"""
        return True

    def set_value(self, key: str, value: str) -> None:
        """Set environment variable (for testing)"""
        os.environ[key] = value
        logger.debug(f"Set environment variable {key}")

    def unset_value(self, key: str) -> None:
        """Unset environment variable (for testing)"""
        if key in os.environ:
            del os.environ[key]
            logger.debug(f"Unset environment variable {key}")

    def get_all_env_vars(self) -> dict:
        """Get all environment variables (for debugging)"""
        return dict(os.environ)

    def get_env_vars_by_prefix(self, prefix: str) -> dict:
        """Get environment variables with specific prefix"""
        return {
            key: value for key, value in os.environ.items() if key.startswith(prefix)
        }
