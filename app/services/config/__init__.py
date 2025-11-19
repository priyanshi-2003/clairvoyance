"""
Configuration Resolution Service

Hybrid configuration resolution engine that supports:
- Variable classification (core vs non-core)
- Frequency-based caching strategies
- DevCycle API integration
- Redis caching with background refresh
- Fallback to environment variables
"""

from .engine import (
    ConfigurationEngine,
    config_health_check,
    get_config,
    get_config_bool,
    get_config_engine,
    get_config_float,
    get_config_int,
    get_config_str,
    get_multiple_configs,
    invalidate_config_cache,
)
from .models import (
    CacheStats,
    ConfigResolutionResult,
    ConfigValueType,
    ConfigVariable,
    DevCycleConfig,
    FrequencyClass,
    VariableClassification,
    convert_value,
)
from .providers import (
    BaseConfigProvider,
    DevCycleProvider,
    EnvironmentProvider,
    HybridProvider,
)

__all__ = [
    # Main interface
    "get_config",
    "get_config_bool",
    "get_config_int",
    "get_config_float",
    "get_config_str",
    "get_multiple_configs",
    "invalidate_config_cache",
    "config_health_check",
    # Engine
    "ConfigurationEngine",
    "get_config_engine",
    # Models
    "VariableClassification",
    "FrequencyClass",
    "ConfigValueType",
    "ConfigVariable",
    "ConfigResolutionResult",
    "DevCycleConfig",
    "CacheStats",
    "convert_value",
    # Providers
    "BaseConfigProvider",
    "EnvironmentProvider",
    "DevCycleProvider",
    "HybridProvider",
]
