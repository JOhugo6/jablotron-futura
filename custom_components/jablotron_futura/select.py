"""Select platform for Jablotron Futura."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import HUMI_MODE_MAP, VENT_MODE_INV, VENT_MODE_MAP
from .entity import FuturaEntity
from .models import FuturaConfigEntry

PARALLEL_UPDATES = 0


class FuturaVentModeSelect(FuturaEntity, SelectEntity):
    """Vent mode select."""

    _attr_options = list(VENT_MODE_MAP.keys())

    def __init__(self, entry: FuturaConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator, entry, "Vent mode", "vent_mode")

    @property
    def current_option(self) -> str | None:
        return VENT_MODE_INV.get(int(self.coordinator.data.get("mode_raw", 0) or 0), "Off")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_vent_mode(VENT_MODE_MAP[option])


class FuturaHumidityModeSelect(FuturaEntity, SelectEntity):
    """Humidity mode select."""

    _attr_options = list(HUMI_MODE_MAP.keys())

    def __init__(self, entry: FuturaConfigEntry) -> None:
        super().__init__(
            entry.runtime_data.coordinator,
            entry,
            "Humidity mode",
            "humidity_mode",
        )

    @property
    def current_option(self) -> str | None:
        value = float(self.coordinator.data.get("humi_set_raw", 50.0) or 50.0)
        if value < 37.5:
            return "Dry"
        if value < 62.5:
            return "Comfort"
        return "Humid"

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_humidity_target_raw(int(HUMI_MODE_MAP[option] * 10))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FuturaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([FuturaVentModeSelect(entry), FuturaHumidityModeSelect(entry)])
