"""Binary sensors for Jablotron Futura errors and warnings."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import FuturaEntity
from .models import FuturaConfigEntry
from .sensor_visibility import eligible_metrics
from .sensor_names import external_sensor_name_translation
from .models import eligible_button_members
from .status import (
    ERROR_BITS,
    WARNING_BITS,
    STATUS_BITS,
    STATUS_REGISTERS,
    status_details,
    valid_status_value,
)

PARALLEL_UPDATES = 0


def _status_value(data: Any, key: str) -> int | None:
    value = data.get(key) if isinstance(data, Mapping) else None
    return value if valid_status_value(value) else None


@dataclass(frozen=True, kw_only=True)
class BitEntityDescription:
    key: str
    name: str
    source_key: str
    bit: int


class FuturaBitBinarySensor(FuturaEntity, BinarySensorEntity):
    """Bit-based error/warning sensor."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, entry: FuturaConfigEntry, description: BitEntityDescription
    ) -> None:
        super().__init__(
            entry.runtime_data.coordinator,
            entry,
            description.name,
            description.key,
        )
        self.description = description
        del self._attr_name
        self._attr_translation_key = description.key

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None

    @property
    def is_on(self) -> bool | None:
        value = _status_value(self.coordinator.data, self.description.source_key)
        return None if value is None else bool((value >> self.description.bit) & 1)


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
        del self._attr_name
        self._attr_translation_key = key

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None

    @property
    def is_on(self) -> bool | None:
        value = _status_value(self.coordinator.data, self._source_key)
        return None if value is None else bool(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        value = _status_value(data, self._source_key)
        details = status_details(value, STATUS_BITS[self._source_key])
        address = STATUS_REGISTERS[self._source_key]
        words = data.get("status_words", {}) if isinstance(data, Mapping) else {}
        return {
            **super().extra_state_attributes,
            **{
                key: details[key]
                for key in ("valid", "raw", "known_active_bits", "unknown_bits")
            },
            "raw_words": words.get(self._source_key)
            if isinstance(words, Mapping)
            else None,
            "input_registers": [address, address + 1],
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FuturaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[BinarySensorEntity] = [
        FuturaSummaryBinarySensor(entry, "any_error", "Any error", "errors_bits_raw"),
        FuturaSummaryBinarySensor(
            entry, "any_warning", "Any warning", "warnings_bits_raw"
        ),
        FuturaBitBinarySensor(
            entry,
            BitEntityDescription(
                key="emergency_shutdown_active",
                name="Emergency shutdown active",
                source_key="warnings_bits_raw",
                bit=11,
            ),
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

    # Add Futura-managed button active binary sensors
    entities.extend(_build_futura_button_active_entities(entry))

    entities.extend(
        FuturaSlotBinarySensor(entry, slot, "sensor")
        for slot in range(1, 9)
        if "present" in eligible_metrics(entry.runtime_data.coordinator.config, slot)
    )
    async_add_entities(entities)


class FuturaSlotBinarySensor(FuturaEntity, BinarySensorEntity):
    def __init__(self, entry: FuturaConfigEntry, slot: int, kind: str) -> None:
        suffix = (
            f"ext_btn_active_{slot}" if kind == "button" else f"ext_sens_present_{slot}"
        )
        super().__init__(entry.runtime_data.coordinator, entry, "", suffix)
        self._slot, self._kind = slot, kind
        del self._attr_name
        if kind == "button":
            self._attr_translation_key = "external_button_active"
            self._attr_translation_placeholders = {"slot": str(slot)}
        else:
            self._attr_translation_key, self._attr_translation_placeholders = (
                external_sensor_name_translation(
                    self.coordinator.config, slot, "external_sensor_present"
                )
            )

    @property
    def available(self) -> bool:
        return (
            self.coordinator.readback_available(self._kind, self._slot)
            and self.is_on is not None
        )

    @property
    def is_on(self) -> bool | None:
        states = (
            self.coordinator.sensor_readback
            if self._kind == "sensor"
            else self.coordinator.button_readback
        )
        return states.get(str(self._slot), {}).get(
            "present" if self._kind == "sensor" else "active"
        )


def _build_futura_button_active_entities(
    entry: FuturaConfigEntry,
) -> list[FuturaSlotBinarySensor]:
    return [
        FuturaSlotBinarySensor(entry, slot, "button")
        for slot in range(1, 9)
        if "active"
        in eligible_button_members(entry.runtime_data.coordinator.config, slot)
    ]
