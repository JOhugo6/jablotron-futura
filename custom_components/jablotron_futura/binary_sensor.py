"""Binary sensors for Jablotron Futura errors and warnings."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import FuturaEntity
from .models import FuturaConfigEntry

PARALLEL_UPDATES = 0

ERROR_BITS = {
    0: "Ambient sensor error",
    1: "Indoor sensor error",
    2: "Fresh air sensor error",
    3: "Waste air sensor error",
    4: "Supply fan error",
    5: "Extract fan error",
    6: "Heat exchanger communication error",
    7: "Heat exchanger damper error",
    8: "IO board communication error",
    9: "Supply fan blocked",
    10: "Extract fan blocked",
    11: "CoolBreeze communication error",
    12: "CoolBreeze outdoor unit error",
}

WARNING_BITS = {
    0: "Filter not initialized",
    1: "Filter heavily clogged",
    2: "Filter used too long",
    3: "RTC battery low",
    8: "Low outdoor temperature warning",
    9: "Supply zone configuration warning",
    10: "Extract zone configuration warning",
    11: "Emergency shutdown",
    12: "SuperBreeze communication error",
    13: "General SuperBreeze error",
}


@dataclass(frozen=True, kw_only=True)
class BitEntityDescription:
    key: str
    name: str
    source_key: str
    bit: int


class FuturaBitBinarySensor(FuturaEntity, BinarySensorEntity):
    """Bit-based error/warning sensor."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry: FuturaConfigEntry, description: BitEntityDescription) -> None:
        super().__init__(
            entry.runtime_data.coordinator,
            entry,
            description.name,
            description.key,
        )
        self.description = description

    @property
    def is_on(self) -> bool:
        value = int(self.coordinator.data.get(self.description.source_key, 0) or 0)
        return bool((value >> self.description.bit) & 1)


class FuturaSummaryBinarySensor(FuturaEntity, BinarySensorEntity):
    """Simple coordinator summary binary sensor."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        entry: FuturaConfigEntry,
        key: str,
        name: str,
        source_key: str,
    ) -> None:
        super().__init__(entry.runtime_data.coordinator, entry, name, key)
        self._source_key = source_key

    @property
    def is_on(self) -> bool:
        return bool(int(self.coordinator.data.get(self._source_key, 0) or 0))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FuturaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[BinarySensorEntity] = [
        FuturaSummaryBinarySensor(entry, "any_error", "Any error", "errors_bits_raw"),
        FuturaSummaryBinarySensor(entry, "any_warning", "Any warning", "warnings_bits_raw"),
        FuturaSummaryBinarySensor(
            entry,
            "emergency_shutdown_active",
            "Emergency shutdown active",
            "emergency_shutdown_active",
        ),
    ]

    entities.extend(
        FuturaBitBinarySensor(
            entry,
            BitEntityDescription(
                key=f"error_bit_{bit}",
                name=name,
                source_key="errors_bits_raw",
                bit=bit,
            ),
        )
        for bit, name in ERROR_BITS.items()
    )
    entities.extend(
        FuturaBitBinarySensor(
            entry,
            BitEntityDescription(
                key=f"warning_bit_{bit}",
                name=name,
                source_key="warnings_bits_raw",
                bit=bit,
            ),
        )
        for bit, name in WARNING_BITS.items()
    )

    async_add_entities(entities)
