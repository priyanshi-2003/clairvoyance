"""
Configuration Engine

Main configuration resolution engine that provides the application interface.
Implements the get_config() function with automatic type conversion and caching.
"""

import asyncio
import os
import time
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from .models import (
    DEFAULT_VARIABLE_CONFIGS,
    ConfigResolutionResult,
    ConfigValueType,
    ConfigVariable,
    DevCycleConfig,
    FrequencyClass,
    VariableClassification,
    convert_value,
)
from .providers import DevCycleProvider, EnvironmentProvider, HybridProvider


class ConfigurationEngine:
    """
    Main configuration engine that orchestrates the hybrid resolution strategy.

    Provides the primary get_config() interface for applications.
    """

    def __init__(self):
        self._provider: Optional[HybridProvider] = None
        self._variable_registry: Dict[str, ConfigVariable] = {}
        self._initialized = False
        self._lock = asyncio.Lock()

        # Load default variable configurations
        self._variable_registry.update(DEFAULT_VARIABLE_CONFIGS)

    async def initialize(self, devcycle_config: Optional[DevCycleConfig] = None):
        """Initialize the configuration engine"""
        async with self._lock:
            if self._initialized:
                return

            try:
                # Create providers
                environment_provider = EnvironmentProvider()

                # Create DevCycle config from environment if not provided
                if devcycle_config is None:
                    devcycle_config = DevCycleConfig(
                        name="devcycle",
                        enabled=os.environ.get("DEVCYCLE_ENABLED", "false").lower()
                        == "true",
                        service_token=os.environ.get("DEVCYCLE_SERVICE_TOKEN", ""),
                        api_endpoint=os.environ.get(
                            "DEVCYCLE_API_ENDPOINT", "https://sdk-api.devcycle.com"
                        ),
                        timeout_seconds=float(
                            os.environ.get("DEVCYCLE_TIMEOUT", "5.0")
                        ),
                        user_context={
                            "user_id": os.environ.get("DEVCYCLE_USER_ID", "system"),
                            "email": os.environ.get(
                                "DEVCYCLE_USER_EMAIL", "system@clairvoyance.ai"
                            ),
                            "environment": os.environ.get("ENVIRONMENT", "production"),
                        },
                    )

                devcycle_provider = DevCycleProvider(devcycle_config)

                # Create hybrid provider
                self._provider = HybridProvider(environment_provider, devcycle_provider)

                # Health check
                is_healthy = await self._provider.health_check()
                if is_healthy:
                    logger.info("Configuration engine initialized successfully")
                else:
                    logger.warning(
                        "Configuration engine initialized with some providers unhealthy"
                    )

                self._initialized = True

            except Exception as e:
                logger.error(f"Failed to initialize configuration engine: {e}")
                raise

    async def get_config(
        self,
        key: str,
        default: Any = None,
        value_type: Optional[ConfigValueType] = None,
    ) -> Any:
        """
        Get configuration value with automatic type conversion.

        Args:
            key: Configuration key
            default: Default value if not found
            value_type: Expected value type for conversion

        Returns:
            Configuration value with proper type conversion
        """
        if not self._initialized:
            await self.initialize()

        # Get or create variable configuration
        variable = self._get_or_create_variable(key, default, value_type)

        try:
            # Get value through hybrid provider
            result = await self._provider.get_value(variable)

            if result.success and result.value is not None:
                logger.debug(
                    f"Config resolved: {key}={result.value} (source: {result.source})"
                )
                return result.value
            else:
                logger.debug(
                    f"Config fallback: {key}={default} (error: {result.error})"
                )
                return default

        except Exception as e:
            logger.error(f"Configuration resolution error for {key}: {e}")
            return default

    def _get_or_create_variable(
        self,
        key: str,
        default: Any = None,
        value_type: Optional[ConfigValueType] = None,
    ) -> ConfigVariable:
        """Get existing variable config or create a new one"""

        if key in self._variable_registry:
            variable = self._variable_registry[key]

            # Update default value if provided
            if default is not None and variable.default_value is None:
                variable.default_value = default

            return variable

        # Create new variable configuration with intelligent defaults
        inferred_type = value_type or self._infer_value_type(default)
        classification = self._infer_classification(key)
        frequency_class = self._infer_frequency_class(key)

        variable = ConfigVariable(
            key=key,
            classification=classification,
            frequency_class=frequency_class,
            value_type=inferred_type,
            default_value=default,
            description=f"Auto-generated config for {key}",
        )

        # Register the new variable
        self._variable_registry[key] = variable
        logger.debug(
            f"Created new variable config: {key} ({classification.value}, {frequency_class.value})"
        )

        return variable

    def _infer_value_type(self, default: Any) -> ConfigValueType:
        """Infer value type from default value"""
        if default is None:
            return ConfigValueType.STRING
        elif isinstance(default, bool):
            return ConfigValueType.BOOLEAN
        elif isinstance(default, int):
            return ConfigValueType.INTEGER
        elif isinstance(default, float):
            return ConfigValueType.FLOAT
        elif isinstance(default, (dict, list)):
            return ConfigValueType.JSON
        else:
            return ConfigValueType.STRING

    def _infer_classification(self, key: str) -> VariableClassification:
        """Infer variable classification from key name"""
        core_patterns = [
            "DATABASE",
            "DB_",
            "POSTGRES",
            "REDIS",
            "SECRET",
            "KEY",
            "TOKEN",
            "PASSWORD",
            "CREDENTIALS",
            "HOST",
            "PORT",
            "URL",
            "ENDPOINT",
            "ENVIRONMENT",
            "ENV",
            "AWS_",
            "GCP_",
            "AZURE_",
        ]

        key_upper = key.upper()
        for pattern in core_patterns:
            if pattern in key_upper:
                return VariableClassification.CORE

        return VariableClassification.NON_CORE

    def _infer_frequency_class(self, key: str) -> FrequencyClass:
        """Infer frequency class from key name"""
        high_frequency_patterns = [
            "ENABLE_",
            "DISABLE_",
            "MAX_",
            "MIN_",
            "LIMIT_",
            "THRESHOLD_",
            "FEATURE_",
            "FLAG_",
            "TOGGLE_",
        ]

        low_frequency_patterns = ["CONFIG_", "SETTING_", "PARAM_", "OPTION_"]

        key_upper = key.upper()

        for pattern in high_frequency_patterns:
            if pattern in key_upper:
                return FrequencyClass.HIGH

        for pattern in low_frequency_patterns:
            if pattern in key_upper:
                return FrequencyClass.LOW

        return FrequencyClass.MEDIUM

    def register_variable(self, variable: ConfigVariable):
        """Register a variable configuration"""
        self._variable_registry[variable.key] = variable
        logger.info(f"Registered variable: {variable.key}")

    def register_variables(self, variables: List[ConfigVariable]):
        """Register multiple variable configurations"""
        for variable in variables:
            self.register_variable(variable)

    async def get_multiple_configs(self, keys: List[str]) -> Dict[str, Any]:
        """Get multiple configuration values efficiently"""
        if not self._initialized:
            await self.initialize()

        variables = [self._get_or_create_variable(key) for key in keys]

        try:
            results = await self._provider.get_multiple_values(variables)

            config_values = {}
            for i, result in enumerate(results):
                key = keys[i]
                if isinstance(result, ConfigResolutionResult) and result.success:
                    config_values[key] = result.value
                else:
                    config_values[key] = variables[i].default_value

            return config_values

        except Exception as e:
            logger.error(f"Multiple config resolution error: {e}")
            return {
                key: self._variable_registry.get(key, {}).get("default_value")
                for key in keys
            }

    async def invalidate_cache(self, key: str) -> bool:
        """Invalidate cached value for a specific key"""
        if not self._initialized:
            return False

        return await self._provider.invalidate_cache(key)

    async def warm_cache(self, keys: Optional[List[str]] = None) -> Dict[str, bool]:
        """Pre-warm cache for specified keys or all registered variables"""
        if not self._initialized:
            await self.initialize()

        if keys is None:
            variables = list(self._variable_registry.values())
        else:
            variables = [self._get_or_create_variable(key) for key in keys]

        return await self._provider.warm_cache(variables)

    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check"""
        if not self._initialized:
            return {"status": "not_initialized"}

        try:
            provider_healthy = await self._provider.health_check()
            stats = self._provider.get_stats()

            return {
                "status": "healthy" if provider_healthy else "degraded",
                "initialized": self._initialized,
                "registered_variables": len(self._variable_registry),
                "provider_stats": stats,
            }

        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def get_variable_registry(self) -> Dict[str, ConfigVariable]:
        """Get all registered variables (for debugging)"""
        return self._variable_registry.copy()

    async def close(self):
        """Close the configuration engine"""
        if self._provider:
            await self._provider.close()
        self._initialized = False
        logger.info("Configuration engine closed")


# Global configuration engine instance
_config_engine: Optional[ConfigurationEngine] = None


async def get_config_engine() -> ConfigurationEngine:
    """Get global configuration engine instance"""
    global _config_engine
    if _config_engine is None:
        _config_engine = ConfigurationEngine()
        await _config_engine.initialize()
    return _config_engine


# Convenience functions for direct usage
async def get_config(
    key: str, default: Any = None, value_type: Optional[ConfigValueType] = None
) -> Any:
    """Get configuration value (main application interface)"""
    engine = await get_config_engine()
    return await engine.get_config(key, default, value_type)


async def get_config_bool(key: str, default: bool = False) -> bool:
    """Get boolean configuration value"""
    return await get_config(key, default, ConfigValueType.BOOLEAN)


async def get_config_int(key: str, default: int = 0) -> int:
    """Get integer configuration value"""
    return await get_config(key, default, ConfigValueType.INTEGER)


async def get_config_float(key: str, default: float = 0.0) -> float:
    """Get float configuration value"""
    return await get_config(key, default, ConfigValueType.FLOAT)


async def get_config_str(key: str, default: str = "") -> str:
    """Get string configuration value"""
    return await get_config(key, default, ConfigValueType.STRING)


async def get_multiple_configs(keys: List[str]) -> Dict[str, Any]:
    """Get multiple configuration values"""
    engine = await get_config_engine()
    return await engine.get_multiple_configs(keys)


async def invalidate_config_cache(key: str) -> bool:
    """Invalidate cached configuration value"""
    engine = await get_config_engine()
    return await engine.invalidate_cache(key)


async def config_health_check() -> Dict[str, Any]:
    """Get configuration system health status"""
    try:
        engine = await get_config_engine()
        return await engine.health_check()
    except Exception as e:
        return {"status": "error", "error": str(e)}
