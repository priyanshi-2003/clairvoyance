# Daily.co Proxy Configuration Fix

## Problem
The Daily.co integration was failing with connection timeouts and HTTP 400 errors because Daily.co API calls were being routed through the AWS proxy configuration.

## Root Cause
- The application was configured to use AWS proxy (`localhost:3128`) for all HTTP requests
- Daily.co API calls were being proxied, causing malformed requests and connection failures
- Daily.co's WebRTC infrastructure requires direct internet access, not proxy routing

## Error Symptoms
```
Time out joining https://juspay.daily.co/GAXJSKUVsCPEt7Xh4R5X
Failed to fetch room information: GET failed: Status(400, Response[status: 400, status_text: Bad Request, url: http://localhost:3128/gs.daily.co/rooms/check/juspay/GAXJSKUVsCPEt7Xh4R5X])
```

## Solution
Fixed proxy configuration in two locations:

### 1. Main Application (`app/main.py`)
Modified to create separate aiohttp sessions:

**Daily.co session**: Direct connection without proxy
```python
# Initialize aiohttp session WITHOUT proxy for Daily API
# Daily.co should not go through proxy as it needs direct WebRTC access
import aiohttp
daily_aiohttp_session = aiohttp.ClientSession()
daily_helpers["rest"] = DailyRESTHelper(
    daily_api_key=DAILY_API_KEY,
    daily_api_url=DAILY_API_URL,
    aiohttp_session=daily_aiohttp_session,
)
```

**Other APIs session**: Uses proxy configuration
```python
# Initialize separate aiohttp session with proxy support for other APIs
aiohttp_session = create_aiohttp_session()
```

### 2. Voice Agent Processes (`app/agents/voice/automatic/__init__.py`)
Removed proxy configuration from WebRTC transport:

**Before:**
```python
# Configure proxy for WebRTC connections if available
proxy_url = get_proxy_config()
if proxy_url:
    logger.info(f"Configuring Daily WebRTC proxy: {proxy_url}")
    try:
        transport._client._client.set_proxy_url(proxy_url)
        logger.info("Daily WebRTC proxy configured successfully")
    except Exception as e:
        logger.error(f"Failed to configure Daily WebRTC proxy: {e}")
```

**After:**
```python
# Skip proxy configuration for Daily WebRTC connections
# WebRTC requires direct internet access and doesn't work through HTTP proxies
logger.info("Skipping proxy configuration for Daily WebRTC - direct connection required")
```

## Result
- Daily.co room creation now works successfully
- WebRTC connections can be established
- Other API calls still use proxy when needed
- No more timeout or 400 errors from Daily.co

## Files Modified
- `app/main.py`: Separated Daily.co and general HTTP client sessions

## Testing
The fix was verified by running the application and confirming:
- Daily room pool initialization succeeds
- Room creation logs show successful URLs
- No proxy-related errors in Daily.co API calls
