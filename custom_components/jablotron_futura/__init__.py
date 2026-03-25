"""The Jablotron Futura integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .bridge import ExternalSensorBridge
from .const import PLATFORMS
from .coordinator import FuturaCoordinator
from .models import FuturaConfigEntry, FuturaRuntimeData


async def async_setup_entry(hass: HomeAssistant, entry: FuturaConfigEntry) -> bool:
    """Set up Jablotron Futura from a config entry."""
    coordinator = FuturaCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:  # noqa: BLE001
        await coordinator.async_close()
        raise ConfigEntryNotReady(str(err)) from err

    bridge = ExternalSensorBridge(hass, entry, coordinator)
    await bridge.async_start()

    entry.runtime_data = FuturaRuntimeData(coordinator=coordinator, bridge=bridge)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FuturaConfigEntry) -> bool:
    """Unload a Jablotron Futura config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.bridge.async_stop()
        await entry.runtime_data.coordinator.async_close()
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: FuturaConfigEntry) -> None:
    """Reload entry after options or data changes."""
    await hass.config_entries.async_reload(entry.entry_id)
