"""
Base Configuration Provider

Abstract base class for all configuration providers.
"""

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from loguru import logger

from ..models import (
    ConfigResolutionResult,
    ConfigValueType,
    ConfigVariable,
    convert_value,
)


class BaseConfigProvider(ABC):
    """Abstract base class for configuration providers"""

    def __init__(self, name: str):
        self.name = name
        self._circuit_breaker_failures = 0
        self._circuit_breaker_last_failure = 0
        self._circuit_breaker_threshold = 5
        self._circuit_breaker_timeout = 60  # seconds

    @abstractmethod
    async def get_value(self, variable: ConfigVariable) -> ConfigResolutionResult:
        """Get configuration value for the given variable"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if provider is healthy"""
        pass

    async def get_value_with_circuit_breaker(
        self, variable: ConfigVariable
    ) -> ConfigResolutionResult:
        """Get value with circuit breaker protection"""
        start_time = time.time()

        # Check circuit breaker
        if self._is_circuit_breaker_open():
            logger.warning(f"Circuit breaker open for provider {self.name}")
            return ConfigResolutionResult(
                key=variable.key,
                value=None,
                source=self.name,
                value_type=variable.value_type,
                resolution_time_ms=(time.time() - start_time) * 1000,
                error="Circuit breaker open",
            )

        try:
            result = await self.get_value(variable)

            # Reset circuit breaker on success
            if result.success:
                self._circuit_breaker_failures = 0
            else:
                self._record_failure()

            return result

        except Exception as e:
            self._record_failure()
            logger.error(f"Provider {self.name} error for key {variable.key}: {e}")

            return ConfigResolutionResult(
                key=variable.key,
                value=None,
                source=self.name,
                value_type=variable.value_type,
                resolution_time_ms=(time.time() - start_time) * 1000,
                error=str(e),
            )

    def _is_circuit_breaker_open(self) -> bool:
        """Check if circuit breaker is open"""
        if self._circuit_breaker_failures < self._circuit_breaker_threshold:
            return False

        # Check if timeout has passed
        if (
            time.time() - self._circuit_breaker_last_failure
            > self._circuit_breaker_timeout
        ):
            # Reset circuit breaker
            self._circuit_breaker_failures = 0
            return False

        return True

    def _record_failure(self):
        """Record a failure for circuit breaker"""
        self._circuit_breaker_failures += 1
        self._circuit_breaker_last_failure = time.time()

        if self._circuit_breaker_failures >= self._circuit_breaker_threshold:
            logger.warning(
                f"Circuit breaker opened for provider {self.name} "
                f"after {self._circuit_breaker_failures} failures"
            )

    def _convert_and_validate_value(
        self, raw_value: Any, variable: ConfigVariable
    ) -> ConfigResolutionResult:
        """Convert and validate the raw value"""
        start_time = time.time()

        try:
            if raw_value is None:
                converted_value = variable.default_value
                source_suffix = "_default" if converted_value is not None else "_null"
            else:
                converted_value = convert_value(raw_value, variable.value_type)
                source_suffix = ""

            return ConfigResolutionResult(
                key=variable.key,
                value=converted_value,
                source=f"{self.name}{source_suffix}",
                value_type=variable.value_type,
                resolution_time_ms=(time.time() - start_time) * 1000,
            )

        except Exception as e:
            logger.error(f"Value conversion error for {variable.key}: {e}")
            return ConfigResolutionResult(
                key=variable.key,
                value=variable.default_value,
                source=f"{self.name}_error",
                value_type=variable.value_type,
                resolution_time_ms=(time.time() - start_time) * 1000,
                error=f"Conversion error: {str(e)}",
            )

    async def get_multiple_values(
        self, variables: list[ConfigVariable]
    ) -> list[ConfigResolutionResult]:
        """Get multiple configuration values concurrently"""
        tasks = [self.get_value_with_circuit_breaker(var) for var in variables]
        return await asyncio.gather(*tasks, return_exceptions=True)

    def get_stats(self) -> dict:
        """Get provider statistics"""
        return {
            "name": self.name,
            "circuit_breaker_failures": self._circuit_breaker_failures,
            "circuit_breaker_open": self._is_circuit_breaker_open(),
            "last_failure_time": self._circuit_breaker_last_failure,
        }
