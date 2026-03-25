"""Shared data models for the Jablotron Futura integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeAlias

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_BRIDGE_ENABLED,
    CONF_BRIDGE_UPDATE_INTERVAL_S,
    CONF_CO2_ENTITY_ID,
    CONF_ENABLED,
    CONF_EXTERNAL_SENSOR_SLOTS,
    CONF_FLOOR_TEMPERATURE_ENTITY_ID,
    CONF_FORCE_RESYNC_EVERY_S,
    CONF_HUMIDITY_ENTITY_ID,
    CONF_LOG_LEVEL_BRIDGE,
    CONF_SHOW_COMMISSIONING_NOTICE,
    CONF_SLOT_NAME,
    CONF_STALE_AFTER_S,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_WRITE_ON_CHANGE_ONLY,
    DEFAULT_BRIDGE_ENABLED,
    DEFAULT_BRIDGE_UPDATE_INTERVAL_S,
    DEFAULT_FORCE_RESYNC_EVERY_S,
    DEFAULT_LOG_LEVEL_BRIDGE,
    DEFAULT_SHOW_COMMISSIONING_NOTICE,
    DEFAULT_STALE_AFTER_S,
    DEFAULT_WRITE_ON_CHANGE_ONLY,
    SLOT_COUNT,
)

if TYPE_CHECKING:
    from .bridge import ExternalSensorBridge
    from .coordinator import FuturaCoordinator


@dataclass(slots=True, frozen=True)
class BridgeOptions:
    """Global bridge options stored in config entry options."""

    bridge_enabled: bool = DEFAULT_BRIDGE_ENABLED
    bridge_update_interval_s: int = DEFAULT_BRIDGE_UPDATE_INTERVAL_S
    stale_after_s: int = DEFAULT_STALE_AFTER_S
    write_on_change_only: bool = DEFAULT_WRITE_ON_CHANGE_ONLY
    force_resync_every_s: int = DEFAULT_FORCE_RESYNC_EVERY_S
    log_level_bridge: str = DEFAULT_LOG_LEVEL_BRIDGE
    show_commissioning_notice: bool = DEFAULT_SHOW_COMMISSIONING_NOTICE

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "BridgeOptions":
        """Build bridge options from config entry options."""
        if data is None:
            data = {}
        return cls(
            bridge_enabled=bool(data.get(CONF_BRIDGE_ENABLED, DEFAULT_BRIDGE_ENABLED)),
            bridge_update_interval_s=int(
                data.get(
                    CONF_BRIDGE_UPDATE_INTERVAL_S, DEFAULT_BRIDGE_UPDATE_INTERVAL_S
                )
            ),
            stale_after_s=int(data.get(CONF_STALE_AFTER_S, DEFAULT_STALE_AFTER_S)),
            write_on_change_only=bool(
                data.get(CONF_WRITE_ON_CHANGE_ONLY, DEFAULT_WRITE_ON_CHANGE_ONLY)
            ),
            force_resync_every_s=int(
                data.get(CONF_FORCE_RESYNC_EVERY_S, DEFAULT_FORCE_RESYNC_EVERY_S)
            ),
            log_level_bridge=str(
                data.get(CONF_LOG_LEVEL_BRIDGE, DEFAULT_LOG_LEVEL_BRIDGE)
            ),
            show_commissioning_notice=bool(
                data.get(
                    CONF_SHOW_COMMISSIONING_NOTICE, DEFAULT_SHOW_COMMISSIONING_NOTICE
                )
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return options as serializable dictionary."""
        return {
            CONF_BRIDGE_ENABLED: self.bridge_enabled,
            CONF_BRIDGE_UPDATE_INTERVAL_S: self.bridge_update_interval_s,
            CONF_STALE_AFTER_S: self.stale_after_s,
            CONF_WRITE_ON_CHANGE_ONLY: self.write_on_change_only,
            CONF_FORCE_RESYNC_EVERY_S: self.force_resync_every_s,
            CONF_LOG_LEVEL_BRIDGE: self.log_level_bridge,
            CONF_SHOW_COMMISSIONING_NOTICE: self.show_commissioning_notice,
        }


@dataclass(slots=True, frozen=True)
class ExternalSensorSlotConfig:
    """Stored config for one external sensor slot."""

    slot_index: int
    enabled: bool = False
    slot_name: str = ""
    temperature_entity_id: str | None = None
    humidity_entity_id: str | None = None
    co2_entity_id: str | None = None
    floor_temperature_entity_id: str | None = None

    @classmethod
    def from_mapping(
        cls, slot_index: int, data: dict[str, Any] | None
    ) -> "ExternalSensorSlotConfig":
        """Build one slot config from serialized config entry options."""
        if data is None:
            data = {}
        return cls(
            slot_index=slot_index,
            enabled=bool(data.get(CONF_ENABLED, False)),
            slot_name=str(data.get(CONF_SLOT_NAME, "")),
            temperature_entity_id=_normalize_entity_id(
                data.get(CONF_TEMPERATURE_ENTITY_ID)
            ),
            humidity_entity_id=_normalize_entity_id(data.get(CONF_HUMIDITY_ENTITY_ID)),
            co2_entity_id=_normalize_entity_id(data.get(CONF_CO2_ENTITY_ID)),
            floor_temperature_entity_id=_normalize_entity_id(
                data.get(CONF_FLOOR_TEMPERATURE_ENTITY_ID)
            ),
        )

    def has_source(self) -> bool:
        """Return true if at least one metric source is configured."""
        return any(self.entity_ids())

    def entity_ids(self) -> list[str]:
        """Return all configured entity ids for the slot."""
        return [
            entity_id
            for entity_id in (
                self.temperature_entity_id,
                self.humidity_entity_id,
                self.co2_entity_id,
                self.floor_temperature_entity_id,
            )
            if entity_id
        ]

    def as_dict(self) -> dict[str, Any]:
        """Return slot config as serializable dictionary."""
        return {
            CONF_ENABLED: self.enabled,
            CONF_SLOT_NAME: self.slot_name,
            CONF_TEMPERATURE_ENTITY_ID: self.temperature_entity_id,
            CONF_HUMIDITY_ENTITY_ID: self.humidity_entity_id,
            CONF_CO2_ENTITY_ID: self.co2_entity_id,
            CONF_FLOOR_TEMPERATURE_ENTITY_ID: self.floor_temperature_entity_id,
        }


def load_slot_configs(options: dict[str, Any]) -> list[ExternalSensorSlotConfig]:
    """Load all slot configs from config entry options."""
    serialized = options.get(CONF_EXTERNAL_SENSOR_SLOTS, [])
    return [
        ExternalSensorSlotConfig.from_mapping(index, _safe_slot_mapping(serialized, index))
        for index in range(1, SLOT_COUNT + 1)
    ]


def dump_slot_configs(slot_configs: list[ExternalSensorSlotConfig]) -> list[dict[str, Any]]:
    """Serialize slot configs for config entry options."""
    return [slot_config.as_dict() for slot_config in slot_configs]


def default_options() -> dict[str, Any]:
    """Return default options payload for new config entries."""
    bridge_options = BridgeOptions()
    return {
        **bridge_options.as_dict(),
        CONF_EXTERNAL_SENSOR_SLOTS: [
            ExternalSensorSlotConfig(slot_index=index).as_dict()
            for index in range(1, SLOT_COUNT + 1)
        ],
    }


@dataclass(slots=True)
class SlotRuntimeState:
    """Runtime diagnostics state for one slot."""

    slot_index: int
    present: int = 0
    invalidate_mask: int = 0
    temperature_raw: int = 0
    humidity_raw: int = 0
    co2_raw: int = 0
    floor_temperature_raw: int = 0
    last_successful_write_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_error: str | None = None
    last_reason: str | None = None
    pending_write_reason: str | None = None
    last_payload: list[int] = field(default_factory=lambda: [0, 0, 0, 0, 0, 0])
    source_snapshot: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return runtime state as serializable diagnostics payload."""
        return {
            "slot_index": self.slot_index,
            "present": self.present,
            "invalidate_mask": self.invalidate_mask,
            "temperature_raw": self.temperature_raw,
            "humidity_raw": self.humidity_raw,
            "co2_raw": self.co2_raw,
            "floor_temperature_raw": self.floor_temperature_raw,
            "last_successful_write_at": self.last_successful_write_at.isoformat()
            if self.last_successful_write_at
            else None,
            "last_attempt_at": self.last_attempt_at.isoformat()
            if self.last_attempt_at
            else None,
            "last_error": self.last_error,
            "last_reason": self.last_reason,
            "pending_write_reason": self.pending_write_reason,
            "last_payload": list(self.last_payload),
            "source_snapshot": dict(self.source_snapshot),
        }


@dataclass(slots=True)
class FuturaRuntimeData:
    """Runtime objects held on ConfigEntry.runtime_data."""

    coordinator: "FuturaCoordinator"
    bridge: "ExternalSensorBridge"


FuturaConfigEntry: TypeAlias = ConfigEntry[FuturaRuntimeData]


def _normalize_entity_id(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _safe_slot_mapping(serialized: Any, slot_index: int) -> dict[str, Any] | None:
    if not isinstance(serialized, list):
        return None
    if len(serialized) < slot_index:
        return None
    data = serialized[slot_index - 1]
    return data if isinstance(data, dict) else None
