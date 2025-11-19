"""
Configuration Models

Data models for the hybrid configuration resolution engine.
Defines variable classification, frequency classes, and configuration metadata.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Union


class VariableClassification(Enum):
    """Classification of configuration variables"""

    CORE = "core"  # Environment variables only (direct access)
    NON_CORE = "non_core"  # Can use DevCycle or fallback to environment


class FrequencyClass(Enum):
    """Frequency classification for caching strategy"""

    HIGH = "high"  # 50+ calls/sec - Redis cache + background refresh
    MEDIUM = "medium"  # 10-50 calls/sec - Redis cache with longer TTL
    LOW = "low"  # 1-10 calls/sec - Direct API calls (real-time)


class ConfigValueType(Enum):
    """Supported configuration value types"""

    STRING = "string"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"
    JSON = "json"


@dataclass
class ConfigVariable:
    """Configuration variable metadata"""

    key: str
    classification: VariableClassification
    frequency_class: FrequencyClass
    value_type: ConfigValueType
    default_value: Optional[Any] = None
    description: Optional[str] = None

    # Caching configuration
    cache_ttl: Optional[int] = None  # Override default TTL
    refresh_interval: Optional[int] = None  # Override default refresh interval

    # DevCycle specific
    devcycle_key: Optional[str] = None  # Different key in DevCycle if needed

    # Metadata
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.updated_at is None:
            self.updated_at = datetime.utcnow()

        # Set DevCycle key to main key if not specified
        if self.devcycle_key is None:
            self.devcycle_key = self.key

        # Set default cache settings based on frequency class
        if self.cache_ttl is None:
            self.cache_ttl = self._get_default_ttl()

        if self.refresh_interval is None:
            self.refresh_interval = self._get_default_refresh_interval()

    def _get_default_ttl(self) -> int:
        """Get default TTL based on frequency class"""
        ttl_map = {
            FrequencyClass.HIGH: 30,  # 30 seconds
            FrequencyClass.MEDIUM: 300,  # 5 minutes
            FrequencyClass.LOW: 0,  # No caching
        }
        return ttl_map.get(self.frequency_class, 30)

    def _get_default_refresh_interval(self) -> int:
        """Get default refresh interval based on frequency class"""
        interval_map = {
            FrequencyClass.HIGH: 30,  # Refresh every 30 seconds
            FrequencyClass.MEDIUM: 300,  # Refresh every 5 minutes
            FrequencyClass.LOW: 0,  # No background refresh
        }
        return interval_map.get(self.frequency_class, 30)


@dataclass
class ConfigResolutionResult:
    """Result of configuration resolution"""

    key: str
    value: Any
    source: str  # "devcycle", "environment", "default", "cache"
    value_type: ConfigValueType
    cached: bool = False
    cache_hit: bool = False
    resolution_time_ms: float = 0.0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Whether resolution was successful"""
        return self.error is None


@dataclass
class ProviderConfig:
    """Configuration for providers"""

    name: str
    enabled: bool = True
    timeout_seconds: float = 5.0
    retry_attempts: int = 3
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: int = 60

    # Provider-specific config
    config: Dict[str, Any] = None

    def __post_init__(self):
        if self.config is None:
            self.config = {}


@dataclass
class DevCycleConfig(ProviderConfig):
    """DevCycle provider configuration"""

    service_token: str = ""
    api_endpoint: str = "https://sdk-api.devcycle.com"
    user_context: Dict[str, Any] = None

    def __post_init__(self):
        super().__post_init__()
        if self.user_context is None:
            self.user_context = {"user_id": "system", "email": "system@clairvoyance.ai"}


@dataclass
class CacheStats:
    """Cache performance statistics"""

    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    api_calls: int = 0
    errors: int = 0
    avg_resolution_time_ms: float = 0.0

    @property
    def hit_rate(self) -> float:
        """Cache hit rate percentage"""
        if self.total_requests == 0:
            return 0.0
        return (self.cache_hits / self.total_requests) * 100

    @property
    def error_rate(self) -> float:
        """Error rate percentage"""
        if self.total_requests == 0:
            return 0.0
        return (self.errors / self.total_requests) * 100


# Type conversion utilities
def convert_value(value: str, target_type: ConfigValueType) -> Any:
    """Convert string value to target type"""
    if value is None:
        return None

    if target_type == ConfigValueType.STRING:
        return str(value)

    elif target_type == ConfigValueType.BOOLEAN:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on", "enabled")
        return bool(value)

    elif target_type == ConfigValueType.INTEGER:
        return int(value)

    elif target_type == ConfigValueType.FLOAT:
        return float(value)

    elif target_type == ConfigValueType.JSON:
        import json

        if isinstance(value, str):
            return json.loads(value)
        return value

    else:
        return str(value)


# Predefined variable configurations
DEFAULT_VARIABLE_CONFIGS = {
    # Core variables (environment only)
    "ENVIRONMENT": ConfigVariable(
        key="ENVIRONMENT",
        classification=VariableClassification.CORE,
        frequency_class=FrequencyClass.HIGH,
        value_type=ConfigValueType.STRING,
        default_value="production",
        description="Application environment",
    ),
    "DATABASE_URL": ConfigVariable(
        key="DATABASE_URL",
        classification=VariableClassification.CORE,
        frequency_class=FrequencyClass.HIGH,
        value_type=ConfigValueType.STRING,
        description="Database connection URL",
    ),
    # Non-core variables (can use DevCycle)
    "ENABLE_FEATURE_X": ConfigVariable(
        key="ENABLE_FEATURE_X",
        classification=VariableClassification.NON_CORE,
        frequency_class=FrequencyClass.HIGH,
        value_type=ConfigValueType.BOOLEAN,
        default_value=False,
        description="Enable experimental feature X",
    ),
    "MAX_CONCURRENT_SESSIONS": ConfigVariable(
        key="MAX_CONCURRENT_SESSIONS",
        classification=VariableClassification.NON_CORE,
        frequency_class=FrequencyClass.MEDIUM,
        value_type=ConfigValueType.INTEGER,
        default_value=100,
        description="Maximum concurrent user sessions",
    ),
    "API_RATE_LIMIT": ConfigVariable(
        key="API_RATE_LIMIT",
        classification=VariableClassification.NON_CORE,
        frequency_class=FrequencyClass.LOW,
        value_type=ConfigValueType.INTEGER,
        default_value=1000,
        description="API requests per minute limit",
    ),
}
