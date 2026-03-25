"""Diagnostics support for Jablotron Futura."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_HOST, CONF_PORT
from .models import FuturaConfigEntry

TO_REDACT = {CONF_HOST, CONF_PORT, "title", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FuturaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator_data": async_redact_data(runtime.coordinator.data, TO_REDACT),
        "bridge": async_redact_data(runtime.bridge.diagnostics_snapshot(), TO_REDACT),
    }
