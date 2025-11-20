"""
In-Memory Feature Flag Store with DevCycle Integration

This module provides an in-memory store for feature flags that:
1. Loads all flags from DevCycle SDK at startup
2. Updates flags via webhook when changes occur
3. Provides fast in-memory access to flag values
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger


class FeatureFlagStore:
    """In-memory store for feature flags"""

    def __init__(self):
        self._flags: Dict[str, Any] = {}
        self._last_updated: Optional[datetime] = None
        self._lock = asyncio.Lock()

    async def initialize_from_devcycle(self) -> None:
        """Initialize all feature flags from DevCycle SDK at startup"""
        async with self._lock:
            try:
                # Import DevCycle SDK
                import devcycle_python_sdk as devcycle

                # Get DevCycle configuration
                server_key = os.getenv("DEVCYCLE_SERVER_KEY")
                if not server_key:
                    logger.warning(
                        "DEVCYCLE_SERVER_KEY not found - feature flags disabled"
                    )
                    return

                # Initialize DevCycle client (synchronous client for server-side)
                options = devcycle.DevCycleLocalOptions()
                client = devcycle.DevCycleLocalClient(server_key, options)

                # Wait for client to initialize
                import time

                time.sleep(1)  # Give client time to initialize

                # Get all feature flags for the environment
                # Create a user context for fetching flags
                user = devcycle.models.user.DevCycleUser(user_id="system_startup")

                # Get all variables (this gets all feature flags)
                all_variables = client.all_variables(user)

                # Store all flags in memory
                for key, variable in all_variables.items():
                    self._flags[key] = variable.value
                    logger.debug(f"Loaded feature flag: {key} = {variable.value}")

                self._last_updated = datetime.now(timezone.utc)
                logger.info(
                    f"Initialized {len(self._flags)} feature flags from DevCycle"
                )

            except ImportError:
                logger.error("DevCycle SDK not installed - feature flags disabled")
            except Exception as e:
                logger.error(f"Failed to initialize feature flags from DevCycle: {e}")

    async def update_flag_from_webhook(self, webhook_data: Dict[str, Any]) -> None:
        """Update a specific flag from webhook data"""
        async with self._lock:
            try:
                # Extract flag key and new value from webhook
                flag_key = webhook_data.get("key")
                if not flag_key:
                    logger.warning("Webhook missing 'key' field")
                    return

                # Extract new value from changes
                changes = webhook_data.get("changes", [])
                if not changes:
                    logger.warning(f"Webhook for {flag_key} has no changes")
                    return

                change = changes[0]  # Take first change
                new_contents = change.get("newContents", {})
                variations = new_contents.get("variations", [])

                if variations:
                    # Get the first variation's first variable value
                    variation = variations[0]
                    variables = variation.get("variables", [])
                    if variables:
                        new_value = variables[0].get("value")

                        # Update in-memory store
                        old_value = self._flags.get(flag_key)
                        self._flags[flag_key] = new_value
                        self._last_updated = datetime.now(timezone.utc)

                        logger.info(
                            f"Updated feature flag via webhook: {flag_key} = {old_value} -> {new_value}"
                        )
                    else:
                        logger.warning(f"No variables found in webhook for {flag_key}")
                else:
                    logger.warning(f"No variations found in webhook for {flag_key}")

            except Exception as e:
                logger.error(f"Failed to update flag from webhook: {e}")

    def get_flag(self, key: str, default: Any = None) -> Any:
        """Get feature flag value from in-memory store"""
        return self._flags.get(key, default)

    def get_all_flags(self) -> Dict[str, Any]:
        """Get all feature flags"""
        return self._flags.copy()

    def get_flag_count(self) -> int:
        """Get number of loaded flags"""
        return len(self._flags)

    def get_last_updated(self) -> Optional[datetime]:
        """Get last update timestamp"""
        return self._last_updated

    def is_initialized(self) -> bool:
        """Check if store has been initialized"""
        return self._last_updated is not None


# Global feature flag store instance
_feature_store: Optional[FeatureFlagStore] = None


def get_feature_store() -> FeatureFlagStore:
    """Get global feature flag store instance"""
    global _feature_store
    if _feature_store is None:
        _feature_store = FeatureFlagStore()
    return _feature_store


# Convenience functions
def get_feature_flag(key: str, default: Any = None) -> Any:
    """Get feature flag value"""
    store = get_feature_store()
    return store.get_flag(key, default)


def is_feature_enabled(key: str) -> bool:
    """Check if a boolean feature flag is enabled"""
    value = get_feature_flag(key, False)
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on", "enabled")
    return bool(value)
