"""Data update coordinator for Obi EnergyTracker."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ObiEnergyTrackerAPI
from .const import DOMAIN, OPTION_LAST_POWER_PROBE, OPTION_POWER_SOURCE

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)
DAYS_OF_HISTORY = 7


class ObiEnergyTrackerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Data update coordinator for Obi EnergyTracker."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: ObiEnergyTrackerAPI,
        config_entry: Any,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=config_entry,
        )
        self.api = api
        last_probe = config_entry.options.get(OPTION_LAST_POWER_PROBE)
        if isinstance(last_probe, dict):
            self.api.last_probe_summary = last_probe

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API.

        Retrieves:
        - Meter reading (Zählerstand) for the device
        - Hourly energy data for the past 7 days
        """
        try:
            meter = await self.api.async_get_meter_data()
            _LOGGER.debug("Meter data: %s", meter)

            # Fetch hourly data for past days (default 7 days)
            end_date = datetime.now()
            hourly_data = await self.api.async_get_hourly_data(
                start_date=end_date,
                num_days=DAYS_OF_HISTORY,
            )
            _LOGGER.debug(
                "Hourly data fetched: %s", "available" if hourly_data else "none"
            )

            power = None
            power_source = self.config_entry.options.get(OPTION_POWER_SOURCE)
            if isinstance(power_source, dict):
                power = await self.api.async_get_power_data(power_source)
            _LOGGER.debug(
                "Power data fetched: %s", "available" if power is not None else "none"
            )

            _LOGGER.info(
                "Successfully fetched data: meter=%s, hourly_days=%d",
                "available" if meter else "none",
                DAYS_OF_HISTORY,
            )
        except OSError as err:
            _LOGGER.error("Failed to update data: %s", err)
            raise UpdateFailed(f"Failed to update data: {err}") from err

        return {
            "hourly": hourly_data,
            "meter": meter,
            "power": power,
        }
