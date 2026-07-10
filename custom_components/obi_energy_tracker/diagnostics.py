"""Diagnostics support for Obi EnergyTracker."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import ObiEnergyTrackerConfigEntry
from .const import (
    CONF_BRIDGE_ID,
    CONF_COUNTRY,
    CONF_DEVICE_ID,
    OPTION_LAST_POWER_PROBE,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ObiEnergyTrackerConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    api = config_entry.runtime_data.api

    return {
        "config_entry_data": {
            "country": config_entry.data.get(CONF_COUNTRY, "DE"),
            "bridge_id": config_entry.data.get(CONF_BRIDGE_ID),
            "device_id": config_entry.data.get(CONF_DEVICE_ID),
        },
        "api_available": bool(api.token),
        "last_power_probe": api.last_probe_summary
        or config_entry.options.get(OPTION_LAST_POWER_PROBE),
    }
