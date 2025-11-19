# Hybrid Configuration Resolution Engine

## Overview

The Hybrid Configuration Resolution Engine implements a sophisticated configuration management system that combines DevCycle feature flags with environment variables, Redis caching, and intelligent fallback mechanisms. This system follows the architecture diagram provided and delivers high-performance configuration resolution with automatic type conversion.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              APPLICATION LAYER                           │
├──────────────────────────────────────────────────────────────────────────┤
│  Application Code → get_config(key) → type_conversion(string → bool/int) │
└───────────────────────────┬──────────────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────────────┐
│                   VARIABLE CLASSIFICATION DECISION                       │
├──────────────────────────────────────────────────────────────────────────┤
│       Is Core Variable? → YES → Environment (Direct Access Only)         │
│                     │                                                    │
│                    NO                                                    │
│                     │                                                    │
│       Determine Frequency Class:                                          │
│            ├── High-Frequency (hot path)                                  │
│            ├── Medium-Frequency                                            │
│            └── Low-Frequency                                               │
└───────────────────────────┬──────────────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────────────┐
│                        HYBRID RESOLUTION ENGINE                           │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   High-Frequency Variables (50+/sec)                                     │
│     ├── Redis refresh logic                                              │
│     ├── Cache TTL: 30 seconds                                            │
│     └── Background Refresh Thread → DevCycle API every 30s               │
│                                                                          │
│   Medium-Frequency Variables (10-50/sec)                                 │
│     ├── Redis cache with longer TTL (5 minutes)                          │
│     └── Background refresh every 5 minutes                               │
│                                                                          │
│   Low-Frequency Variables (1–2 calls)                                    │
│     └── Always Direct DevCycle API (Real-Time)                           │
│                                                                          │
└───────────────────────────┬──────────────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────────────┐
│                     DEVCYCLE COMMUNICATION LAYER                          │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Hybrid Provider → DevCycle REST API (Service Token)                    │
│                 │                                                        │
│                 ▼                                                        │
│      Response (string value only) → return                               │
│                                                                          │
└───────────────────────────┬──────────────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────────────┐
│                           FALLBACK SYSTEM                                 │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  DevCycle Request Timeout/Error?                                         │
│      ├── YES → Environment Variable (fallback)                           │
│      │        If not found → Default Value                               │
│      └── NO  → Return DevCycle Value                                     │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

## Key Features

### 1. Variable Classification
- **Core Variables**: Sensitive configuration (database URLs, secrets) - environment only
- **Non-Core Variables**: Feature flags, limits, settings - can use DevCycle

### 2. Frequency-Based Caching
- **High Frequency (50+ calls/sec)**: Redis cache + 30s background refresh
- **Medium Frequency (10-50 calls/sec)**: Redis cache + 5min background refresh  
- **Low Frequency (1-10 calls/sec)**: Direct DevCycle API calls

### 3. Intelligent Fallback Chain
```
DevCycle API → Environment Variable → Default Value
```

### 4. Automatic Type Conversion
- String → Boolean, Integer, Float, JSON
- Smart boolean parsing: "true", "1", "yes", "on", "enabled"

## Installation & Setup

### 1. Environment Configuration

Add to your `.env` file:

```bash
# DevCycle Configuration
DEVCYCLE_ENABLED=true
DEVCYCLE_SERVICE_TOKEN="your_service_token_here"
DEVCYCLE_API_ENDPOINT="https://sdk-api.devcycle.com"
DEVCYCLE_TIMEOUT=5.0
DEVCYCLE_USER_ID="system"
DEVCYCLE_USER_EMAIL="system@clairvoyance.ai"

# Hybrid Configuration Engine
HYBRID_CONFIG_ENABLED=true
HYBRID_CONFIG_CACHE_NAMESPACE="config"
HYBRID_CONFIG_HIGH_FREQUENCY_TTL=30
HYBRID_CONFIG_MEDIUM_FREQUENCY_TTL=300
HYBRID_CONFIG_HIGH_FREQUENCY_REFRESH=30
HYBRID_CONFIG_MEDIUM_FREQUENCY_REFRESH=300

# Redis (required for caching)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
```

### 2. Redis Setup

Ensure Redis is running:
```bash
# Using Docker
docker run -d -p 6379:6379 redis:alpine

# Or install locally
brew install redis  # macOS
sudo apt install redis-server  # Ubuntu
```

## Usage Examples

### Basic Configuration Access

```python
from app.services.config import get_config, get_config_bool, get_config_int

# Simple usage with automatic type conversion
async def example_usage():
    # Boolean configuration
    feature_enabled = await get_config_bool("ENABLE_NEW_FEATURE", False)
    
    # Integer configuration  
    max_connections = await get_config_int("MAX_CONNECTIONS", 100)
    
    # String configuration with fallback
    api_endpoint = await get_config("API_ENDPOINT", "https://api.example.com")
    
    # Multiple configurations at once
    configs = await get_multiple_configs([
        "ENABLE_NEW_FEATURE", 
        "MAX_CONNECTIONS", 
        "API_ENDPOINT"
    ])
```

### Advanced Configuration Management

```python
from app.services.config import (
    ConfigVariable, 
    VariableClassification, 
    FrequencyClass, 
    ConfigValueType,
    get_config_engine
)

async def advanced_usage():
    engine = await get_config_engine()
    
    # Register custom variable configuration
    custom_var = ConfigVariable(
        key="CUSTOM_FEATURE_FLAG",
        classification=VariableClassification.NON_CORE,
        frequency_class=FrequencyClass.HIGH,
        value_type=ConfigValueType.BOOLEAN,
        default_value=False,
        description="Custom feature flag with high frequency access"
    )
    
    engine.register_variable(custom_var)
    
    # Use the configured variable
    value = await get_config("CUSTOM_FEATURE_FLAG", False)
```

### Health Monitoring

```python
from app.services.config import config_health_check

async def monitor_config_system():
    health = await config_health_check()
    
    print(f"Status: {health['status']}")
    print(f"Cache Hit Rate: {health['provider_stats']['cache_stats']['hit_rate']:.1f}%")
    print(f"Total Requests: {health['provider_stats']['cache_stats']['total_requests']}")
```

## Variable Classification Rules

The system automatically classifies variables based on naming patterns:

### Core Variables (Environment Only)
Variables containing these patterns are classified as CORE:
- `DATABASE`, `DB_`, `POSTGRES`, `REDIS`
- `SECRET`, `KEY`, `TOKEN`, `PASSWORD`, `CREDENTIALS`
- `HOST`, `PORT`, `URL`, `ENDPOINT`
- `ENVIRONMENT`, `ENV`
- `AWS_`, `GCP_`, `AZURE_`

### Frequency Classification
- **High Frequency**: `ENABLE_`, `DISABLE_`, `MAX_`, `MIN_`, `LIMIT_`, `THRESHOLD_`, `FEATURE_`, `FLAG_`, `TOGGLE_`
- **Low Frequency**: `CONFIG_`, `SETTING_`, `PARAM_`, `OPTION_`
- **Medium Frequency**: Everything else

## Performance Characteristics

### Caching Performance
- **Cache Hit**: ~1-2ms response time
- **Cache Miss**: ~50-100ms (includes DevCycle API call)
- **Environment Fallback**: ~0.1ms response time

### Background Refresh
- High-frequency variables refreshed every 30 seconds
- Medium-frequency variables refreshed every 5 minutes
- Distributed locking prevents duplicate refresh operations

### Circuit Breaker
- Opens after 5 consecutive failures
- 60-second timeout before retry
- Automatic fallback to environment variables

## Testing

Run the comprehensive test suite:

```bash
python test_hybrid_config.py
```

The test suite covers:
- ✅ Basic configuration resolution
- ✅ Multiple configuration fetching
- ✅ Variable classification and frequency detection
- ✅ Type conversion (string → bool/int/float)
- ✅ Caching behavior
- ✅ Fallback to environment variables
- ✅ System health monitoring

## Integration with Existing Code

### Replacing Environment Variable Access

**Before:**
```python
import os

# Old way
enable_feature = os.environ.get("ENABLE_FEATURE", "false").lower() == "true"
max_connections = int(os.environ.get("MAX_CONNECTIONS", "100"))
```

**After:**
```python
from app.services.config import get_config_bool, get_config_int

# New way with hybrid resolution
enable_feature = await get_config_bool("ENABLE_FEATURE", False)
max_connections = await get_config_int("MAX_CONNECTIONS", 100)
```

### Gradual Migration Strategy

1. **Phase 1**: Install hybrid config system alongside existing code
2. **Phase 2**: Migrate non-critical configuration variables
3. **Phase 3**: Migrate feature flags and toggles
4. **Phase 4**: Full migration with DevCycle integration

## Monitoring & Observability

### Health Check Endpoint

Add to your FastAPI application:

```python
from app.services.config import config_health_check

@app.get("/health/config")
async def config_health():
    return await config_health_check()
```

### Metrics Available
- Cache hit/miss rates
- API call frequency
- Error rates
- Response times
- Circuit breaker status

### Logging

The system provides comprehensive logging:
- Configuration resolution paths
- Cache hits/misses
- DevCycle API calls
- Fallback activations
- Error conditions

## Troubleshooting

### Common Issues

1. **Redis Connection Failed**
   ```
   Solution: Ensure Redis is running and accessible
   Check: REDIS_HOST and REDIS_PORT configuration
   ```

2. **DevCycle API Errors**
   ```
   Solution: Verify DEVCYCLE_SERVICE_TOKEN is valid
   Check: Network connectivity to DevCycle API
   ```

3. **Slow Configuration Access**
   ```
   Solution: Check Redis performance and network latency
   Monitor: Cache hit rates and background refresh status
   ```

### Debug Mode

Enable debug logging:
```python
import logging
logging.getLogger("app.services.config").setLevel(logging.DEBUG)
```

## Security Considerations

### Core Variable Protection
- Core variables (secrets, database URLs) never sent to external services
- Always resolved from environment variables only
- Automatic classification based on naming patterns

### DevCycle Integration Security
- Service token authentication
- HTTPS-only communication
- Circuit breaker prevents API abuse
- Fallback ensures availability during outages

### Redis Security
- Namespace isolation prevents key conflicts
- TTL-based automatic cleanup
- Optional Redis AUTH support

## Performance Tuning

### Cache Configuration
```bash
# Optimize for your workload
HYBRID_CONFIG_HIGH_FREQUENCY_TTL=30      # Reduce for more real-time updates
HYBRID_CONFIG_MEDIUM_FREQUENCY_TTL=300   # Increase for better performance
HYBRID_CONFIG_HIGH_FREQUENCY_REFRESH=30  # Match TTL for seamless refresh
```

### Redis Optimization
```bash
# Redis performance tuning
REDIS_POOL_SIZE=10
REDIS_MAX_OVERFLOW=20
REDIS_POOL_RECYCLE=3600
```

## Future Enhancements

### Planned Features
- [ ] Configuration change webhooks
- [ ] A/B testing integration
- [ ] Configuration audit logging
- [ ] Multi-environment support
- [ ] Configuration validation schemas
- [ ] Real-time configuration updates via WebSocket

### DevCycle Advanced Features
- [ ] User targeting and segmentation
- [ ] Gradual rollouts and canary releases
- [ ] Configuration analytics and insights
- [ ] Integration with CI/CD pipelines

## Support

For issues and questions:
1. Check the test suite output: `python test_hybrid_config.py`
2. Review logs for error details
3. Verify environment configuration
4. Check Redis and DevCycle connectivity

## License

This implementation is part of the Clairvoyance project and follows the same licensing terms.
