"""Switch platform for Jablotron Futura."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import FuturaEntity
from .models import FuturaConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class FuturaSwitchDescription:
    key: str
    name: str
    register_key: str
    available_key: str | None = None


SWITCH_DESCRIPTIONS = (
    FuturaSwitchDescription(
        key="time_program_raw",
        name="Time program",
        register_key="time_program_raw",
    ),
    FuturaSwitchDescription(
        key="bypass_enable_raw",
        name="Bypass enabled",
        register_key="bypass_enable_raw",
        available_key="bypass_available",
    ),
    FuturaSwitchDescription(
        key="heating_enable_raw",
        name="Heating enabled",
        register_key="heating_enable_raw",
        available_key="heating_available",
    ),
    FuturaSwitchDescription(
        key="cooling_enable_raw",
        name="Cooling enabled",
        register_key="cooling_enable_raw",
        available_key="cooling_available",
    ),
    FuturaSwitchDescription(
        key="comfort_enable_raw",
        name="Comfort mode",
        register_key="comfort_enable_raw",
    ),
)


class FuturaRegisterSwitch(FuturaEntity, SwitchEntity):
    """Switch backed by one holding register."""

    def __init__(self, entry: FuturaConfigEntry, description: FuturaSwitchDescription) -> None:
        super().__init__(
            entry.runtime_data.coordinator, entry, description.name, f"switch_{description.key}"
        )
        self.description = description

    @property
    def is_on(self) -> bool:
        return int(self.coordinator.data.get(self.description.key, 0) or 0) == 1

    @property
    def available(self) -> bool:
        if self.description.available_key is None:
            return super().available
        return super().available and bool(
            self.coordinator.data.get(self.description.available_key, False)
        )

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_switch_key(self.description.register_key, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_switch_key(self.description.register_key, False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FuturaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [FuturaRegisterSwitch(entry, description) for description in SWITCH_DESCRIPTIONS]
    )
