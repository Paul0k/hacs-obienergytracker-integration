"""The obienergytracker integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ObiEnergyTrackerAPI
from .const import (
    CONF_BRIDGE_ID,
    CONF_COUNTRY,
    CONF_DEVICE_ID,
    DOMAIN,
    OPTION_LAST_POWER_PROBE,
    OPTION_POWER_SOURCE,
)
from .coordinator import ObiEnergyTrackerCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]
SERVICE_DEBUG_GET = "debug_get"
SERVICE_PROBE_POWER_ENDPOINTS = "probe_power_endpoints"
SERVICE_ENTRY_ID = "entry_id"
SERVICE_PATH = "path"
SERVICE_PARAMS = "params"


type ObiEnergyTrackerConfigEntry = ConfigEntry[ObiEnergyTrackerCoordinator]


def _get_entry_coordinator(
    hass: HomeAssistant, entry_id: str
) -> ObiEnergyTrackerCoordinator:
    """Return a loaded OBI entry coordinator for a service call."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN or entry.runtime_data is None:
        raise vol.Invalid(f"No loaded {DOMAIN} config entry for {entry_id}")
    return entry.runtime_data


async def _async_handle_debug_get(
    hass: HomeAssistant, service_data: dict[str, Any]
) -> None:
    """Run a user-selected safe debug GET against the OBI API."""
    coordinator = _get_entry_coordinator(hass, service_data[SERVICE_ENTRY_ID])
    await coordinator.api.async_debug_get(
        service_data[SERVICE_PATH], service_data.get(SERVICE_PARAMS)
    )


async def _async_handle_probe_power_endpoints(
    hass: HomeAssistant, service_data: dict[str, Any]
) -> None:
    """Probe known endpoints and persist a confirmed source, if found."""
    entry_id = service_data[SERVICE_ENTRY_ID]
    coordinator = _get_entry_coordinator(hass, entry_id)
    summary = await coordinator.api.async_probe_power_endpoints()
    source = summary["selected_source"]

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise vol.Invalid(f"No config entry for {entry_id}")
    options = dict(entry.options)
    options[OPTION_LAST_POWER_PROBE] = summary
    if isinstance(source, dict):
        options[OPTION_POWER_SOURCE] = source
    hass.config_entries.async_update_entry(entry, options=options)

    if not isinstance(source, dict):
        _LOGGER.info("No OBI API power source was found; existing configuration unchanged")
        return
    _LOGGER.info("Confirmed OBI power source %s; reloading integration", source)
    await hass.config_entries.async_reload(entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the integration-wide debugging services once."""
    if hass.services.has_service(DOMAIN, SERVICE_DEBUG_GET):
        return

    async def async_handle_debug_get(call: ServiceCall) -> None:
        """Handle the debug GET service call."""
        await _async_handle_debug_get(hass, dict(call.data))

    async def async_handle_probe_power_endpoints(call: ServiceCall) -> None:
        """Handle the power endpoint probe service call."""
        await _async_handle_probe_power_endpoints(hass, dict(call.data))

    hass.services.async_register(
        DOMAIN,
        SERVICE_DEBUG_GET,
        async_handle_debug_get,
        schema=vol.Schema(
            {
                vol.Required(SERVICE_ENTRY_ID): str,
                vol.Required(SERVICE_PATH): str,
                vol.Optional(SERVICE_PARAMS, default={}): dict,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PROBE_POWER_ENDPOINTS,
        async_handle_probe_power_endpoints,
        schema=vol.Schema({vol.Required(SERVICE_ENTRY_ID): str}),
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ObiEnergyTrackerConfigEntry
) -> bool:
    """Set up obienergytracker from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    _async_register_services(hass)

    # Create API client
    session = async_get_clientsession(hass)
    api = ObiEnergyTrackerAPI(
        session=session,
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        country=entry.data.get(CONF_COUNTRY, "DE"),
        bridge_id=entry.data.get(CONF_BRIDGE_ID),
        device_id=entry.data.get(CONF_DEVICE_ID),
    )

    # Authenticate
    if not await api.async_login():
        _LOGGER.error("Failed to authenticate with Obi EnergyTracker")
        return False

    # Create coordinator
    coordinator = ObiEnergyTrackerCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ObiEnergyTrackerConfigEntry
) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
