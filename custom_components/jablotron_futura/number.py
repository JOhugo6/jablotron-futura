"""Number platform for Jablotron Futura."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import FuturaEntity
from .models import FuturaConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class FuturaNumberDescription:
    key: str
    name: str
    register_key: str
    min_value: float
    max_value: float
    step: float
    unit: str | None = None
    multiplier: int = 1


NUMBER_DESCRIPTIONS = (
    FuturaNumberDescription(
        key="temp_set_raw",
        name="Temperature setpoint",
        register_key="temp_set_raw",
        min_value=15.0,
        max_value=28.0,
        step=0.5,
        unit=UnitOfTemperature.CELSIUS,
        multiplier=10,
    ),
    FuturaNumberDescription(
        key="boost_remaining_min",
        name="Boost minutes",
        register_key="boost_remaining_s",
        min_value=0,
        max_value=120,
        step=15,
        unit="min",
        multiplier=60,
    ),
    FuturaNumberDescription(
        key="circulation_remaining_min",
        name="Circulation minutes",
        register_key="circulation_remaining_s",
        min_value=0,
        max_value=120,
        step=1,
        unit="min",
        multiplier=60,
    ),
    FuturaNumberDescription(
        key="night_remaining_h",
        name="Night hours",
        register_key="night_remaining_s",
        min_value=0,
        max_value=10,
        step=1,
        unit="h",
        multiplier=3600,
    ),
    FuturaNumberDescription(
        key="party_remaining_h",
        name="Party hours",
        register_key="party_remaining_s",
        min_value=0,
        max_value=8,
        step=1,
        unit="h",
        multiplier=3600,
    ),
)


class FuturaRegisterNumber(FuturaEntity, NumberEntity):
    """Number backed by one holding register."""

    def __init__(self, entry: FuturaConfigEntry, description: FuturaNumberDescription) -> None:
        super().__init__(
            entry.runtime_data.coordinator, entry, description.name, f"number_{description.key}"
        )
        self.description = description
        self._attr_native_min_value = description.min_value
        self._attr_native_max_value = description.max_value
        self._attr_native_step = description.step
        if description.unit:
            self._attr_native_unit_of_measurement = description.unit

    @property
    def native_value(self) -> float | None:
        return float(self.coordinator.data.get(self.description.key, 0) or 0)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_number_key(
            self.description.register_key,
            int(round(value * self.description.multiplier)),
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FuturaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [FuturaRegisterNumber(entry, description) for description in NUMBER_DESCRIPTIONS]
    )
