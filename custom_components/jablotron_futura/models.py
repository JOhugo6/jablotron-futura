"""Shared data models for the Jablotron Futura integration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeAlias

from homeassistant.config_entries import ConfigEntry

from .const import (
    BUTTON_MODE_BOOST,
    CONF_BRIDGE_ENABLED,
    CONF_BRIDGE_UPDATE_INTERVAL_S,
    CONF_BUTTON_CONFIGS,
    CONF_BUTTON_IDS,
    CONF_BUTTON_INDEX,
    CONF_BUTTON_MODE,
    CONF_CO2_ENTITY_ID,
    CONF_DAMPER_NAMES,
    CONF_DEFAULT_TIMER_SECONDS,
    CONF_DEVICE_VARIANT,
    CONF_ENABLED,
    CONF_AREA_ID,
    CONF_ETHERNET_MAC,
    CONF_EXT_BUTTON_MODE,
    CONF_EXTERNAL_SENSOR_SLOTS,
    CONF_EXTERNAL_SENSOR_MODE,
    CONF_EXTERNAL_BUTTONS_ENABLED,
    CONF_FLOOR_TEMPERATURE_ENTITY_ID,
    CONF_FORCE_RESYNC_EVERY_S,
    CONF_FIRMWARE_REVISION,
    CONF_HARDWARE_REVISION,
    CONF_HUMIDITY_ENTITY_ID,
    CONF_LOG_LEVEL_BRIDGE,
    CONF_MAX_ACTIVE_SECONDS,
    CONF_ALFA_INDEX,
    CONF_READ_INTERVAL_MS,
    CONF_SENSOR_MODE,
    CONF_SERIAL_NUMBER,
    CONF_SHOW_COMMISSIONING_NOTICE,
    CONF_SLOT_NAME,
    CONF_STALE_AFTER_S,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_SUPPLY_DAMPER_IDS,
    CONF_EXHAUST_DAMPER_IDS,
    CONF_VARIOBREEZE,
    CONF_WRITEBACK_ENABLED,
    CONF_WRITE_INTERVAL_MS,
    CONF_WRITE_ON_CHANGE_ONLY,
    CONF_ZONE_CONFIGS,
    CONF_ZONE_ENABLED,
    CONF_ZONE_INDEX,
    CONF_ZONE_NAME,
    CONF_ZONE_TYPE,
    DEFAULT_BRIDGE_ENABLED,
    DEFAULT_BRIDGE_UPDATE_INTERVAL_S,
    DEFAULT_BUTTON_MAX_ACTIVE_SECONDS,
    DEFAULT_EXTERNAL_BUTTONS_ENABLED,
    DEFAULT_EXTERNAL_SENSOR_MODE,
    DEFAULT_FORCE_RESYNC_EVERY_S,
    DEFAULT_LOG_LEVEL_BRIDGE,
    DEFAULT_READ_INTERVAL_MS,
    DEFAULT_SHOW_COMMISSIONING_NOTICE,
    DEFAULT_STALE_AFTER_S,
    DEFAULT_WRITE_INTERVAL_MS,
    DEFAULT_WRITE_ON_CHANGE_ONLY,
    EXT_BUTTON_MODE_HA_CONTROL,
    EXT_BUTTON_MODE_NONE,
    EXTERNAL_SENSOR_MODE_HA_WRITEBACK,
    EXTERNAL_SENSOR_MODE_OBSERVE_ONLY,
    MAX_BUTTONS_PER_ZONE,
    SENSOR_MODE_HA_WRITEBACK,
    SENSOR_MODE_NONE,
    SENSOR_MODE_READ,
    SLOT_COUNT,
    ZONE_COUNT,
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
            bridge_update_interval_s=derive_bridge_update_interval_s(data),
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


@dataclass(slots=True, frozen=True)
class DeviceIdentity:
    """Stored device identity persisted on the config entry."""

    device_variant: str = ""
    serial_number: str = ""
    ethernet_mac: str = ""
    hardware_revision: str = ""
    firmware_revision: str = ""

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "DeviceIdentity":
        """Build the identity model from config entry data."""
        if data is None:
            data = {}
        return cls(
            device_variant=str(data.get(CONF_DEVICE_VARIANT, "")),
            serial_number=str(data.get(CONF_SERIAL_NUMBER, "")),
            ethernet_mac=str(data.get(CONF_ETHERNET_MAC, "")),
            hardware_revision=str(data.get(CONF_HARDWARE_REVISION, "")),
            firmware_revision=str(data.get(CONF_FIRMWARE_REVISION, "")),
        )

    def is_complete(self) -> bool:
        """Return true when all required identity fields are available."""
        return all(
            (
                self.device_variant,
                self.serial_number,
                self.ethernet_mac,
                self.hardware_revision,
                self.firmware_revision,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        """Return identity as a serializable mapping."""
        return {
            CONF_DEVICE_VARIANT: self.device_variant,
            CONF_SERIAL_NUMBER: self.serial_number,
            CONF_ETHERNET_MAC: self.ethernet_mac,
            CONF_HARDWARE_REVISION: self.hardware_revision,
            CONF_FIRMWARE_REVISION: self.firmware_revision,
        }


@dataclass(slots=True, frozen=True)
class ZoneButtonConfig:
    """Stored config for one zone-level external button."""

    button_index: int
    enabled: bool = False
    button_mode: str = BUTTON_MODE_BOOST
    max_active_seconds: int = DEFAULT_BUTTON_MAX_ACTIVE_SECONDS

    @classmethod
    def from_mapping(
        cls, button_index: int, data: dict[str, Any] | None
    ) -> "ZoneButtonConfig":
        """Build one zone button config from serialized options."""
        if data is None:
            data = {}
        return cls(
            button_index=button_index,
            enabled=bool(data.get(CONF_ENABLED, False)),
            button_mode=str(data.get(CONF_BUTTON_MODE, BUTTON_MODE_BOOST)),
            max_active_seconds=int(
                data.get(CONF_MAX_ACTIVE_SECONDS, DEFAULT_BUTTON_MAX_ACTIVE_SECONDS)
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a serializable representation of the button config."""
        return {
            CONF_BUTTON_INDEX: self.button_index,
            CONF_ENABLED: self.enabled,
            CONF_BUTTON_MODE: self.button_mode,
            CONF_MAX_ACTIVE_SECONDS: self.max_active_seconds,
        }


@dataclass(slots=True, frozen=True)
class ZoneV2Config:
    """v2 zone config stored per supply_N / exhaust_N key."""

    zone_key: str  # "supply_1" .. "supply_8", "exhaust_1" .. "exhaust_8"
    zone_index: int  # 1-8
    zone_type: str  # "supply" or "exhaust"
    enabled: bool = False
    name: str = ""
    area_id: str | None = None
    damper_names: tuple[tuple[int, str], ...] = ()
    # Per-zone sensor mode (supply zones only): none / read / ha_writeback
    sensor_mode: str = SENSOR_MODE_NONE
    temperature_entity_id: str | None = None
    humidity_entity_id: str | None = None
    co2_entity_id: str | None = None
    floor_temperature_entity_id: str | None = None
    # Per-zone external button mode (exhaust zones only): none / futura / ha_control
    ext_button_mode: str = EXT_BUTTON_MODE_NONE
    button_type: str = BUTTON_MODE_BOOST
    default_timer_seconds: int = DEFAULT_BUTTON_MAX_ACTIVE_SECONDS

    @classmethod
    def from_mapping(cls, zone_key: str, data: dict[str, Any] | None) -> "ZoneV2Config":
        """Build one v2 zone config from serialized data."""
        if data is None:
            data = {}
        parts = zone_key.split("_", 1)
        zone_type = parts[0]
        zone_index = int(parts[1])
        return cls(
            zone_key=zone_key,
            zone_index=zone_index,
            zone_type=zone_type,
            enabled=bool(data.get(CONF_ZONE_ENABLED, False)),
            name=str(data.get(CONF_ZONE_NAME, "")),
            area_id=_normalize_entity_id(data.get(CONF_AREA_ID)),
            damper_names=_normalize_damper_name_tuple(data.get(CONF_DAMPER_NAMES)),
            sensor_mode=str(data.get(CONF_SENSOR_MODE, SENSOR_MODE_NONE)),
            temperature_entity_id=_normalize_entity_id(
                data.get(CONF_TEMPERATURE_ENTITY_ID)
            ),
            humidity_entity_id=_normalize_entity_id(data.get(CONF_HUMIDITY_ENTITY_ID)),
            co2_entity_id=_normalize_entity_id(data.get(CONF_CO2_ENTITY_ID)),
            floor_temperature_entity_id=_normalize_entity_id(
                data.get(CONF_FLOOR_TEMPERATURE_ENTITY_ID)
            ),
            ext_button_mode=str(data.get(CONF_EXT_BUTTON_MODE, EXT_BUTTON_MODE_NONE)),
            button_type=str(data.get(CONF_BUTTON_MODE, BUTTON_MODE_BOOST)),
            default_timer_seconds=int(
                data.get(CONF_DEFAULT_TIMER_SECONDS, DEFAULT_BUTTON_MAX_ACTIVE_SECONDS)
            ),
        )

    @property
    def is_supply(self) -> bool:
        return self.zone_type == "supply"

    @property
    def is_exhaust(self) -> bool:
        return self.zone_type == "exhaust"

    @property
    def damper_name_map(self) -> dict[int, str]:
        """Return configured damper names keyed by zone-local damper index."""
        return dict(self.damper_names)

    def as_dict(self) -> dict[str, Any]:
        """Return zone config as serializable dictionary."""
        return {
            CONF_ZONE_ENABLED: self.enabled,
            CONF_ZONE_NAME: self.name,
            CONF_ZONE_TYPE: self.zone_type,
            CONF_ZONE_INDEX: self.zone_index,
            CONF_AREA_ID: self.area_id,
            CONF_DAMPER_NAMES: {
                str(damper_index): name for damper_index, name in self.damper_names
            },
            CONF_SENSOR_MODE: self.sensor_mode,
            CONF_TEMPERATURE_ENTITY_ID: self.temperature_entity_id,
            CONF_HUMIDITY_ENTITY_ID: self.humidity_entity_id,
            CONF_CO2_ENTITY_ID: self.co2_entity_id,
            CONF_FLOOR_TEMPERATURE_ENTITY_ID: self.floor_temperature_entity_id,
            CONF_EXT_BUTTON_MODE: self.ext_button_mode,
            CONF_BUTTON_MODE: self.button_type,
            CONF_DEFAULT_TIMER_SECONDS: self.default_timer_seconds,
        }


@dataclass(slots=True, frozen=True)
class ZoneConfig:
    """Stored configuration for one Futura zone."""

    zone_index: int
    enabled: bool = False
    zone_name: str = ""
    area_id: str | None = None
    supply_damper_ids: tuple[int, ...] = ()
    exhaust_damper_ids: tuple[int, ...] = ()
    button_ids: tuple[int, ...] = ()
    alfa_index: int | None = None
    writeback_enabled: bool = False
    temperature_entity_id: str | None = None
    humidity_entity_id: str | None = None
    co2_entity_id: str | None = None
    button_configs: tuple[ZoneButtonConfig, ...] = ()

    @classmethod
    def from_mapping(cls, zone_index: int, data: dict[str, Any] | None) -> "ZoneConfig":
        """Build one zone config from serialized config entry options."""
        if data is None:
            data = {}

        button_ids = _normalize_int_tuple(data.get(CONF_BUTTON_IDS))
        raw_button_configs = data.get(CONF_BUTTON_CONFIGS, [])
        button_count = min(
            MAX_BUTTONS_PER_ZONE,
            max(len(button_ids), len(raw_button_configs)),
        )
        button_configs = tuple(
            ZoneButtonConfig.from_mapping(
                index, _safe_index_mapping(raw_button_configs, index)
            )
            for index in range(1, button_count + 1)
        )
        return cls(
            zone_index=zone_index,
            enabled=bool(data.get(CONF_ZONE_ENABLED, False)),
            zone_name=str(data.get(CONF_ZONE_NAME, "")),
            area_id=_normalize_entity_id(data.get(CONF_AREA_ID)),
            supply_damper_ids=_normalize_int_tuple(data.get(CONF_SUPPLY_DAMPER_IDS)),
            exhaust_damper_ids=_normalize_int_tuple(data.get(CONF_EXHAUST_DAMPER_IDS)),
            button_ids=button_ids,
            alfa_index=_normalize_optional_int(data.get(CONF_ALFA_INDEX)),
            writeback_enabled=bool(data.get(CONF_WRITEBACK_ENABLED, False)),
            temperature_entity_id=_normalize_entity_id(
                data.get(CONF_TEMPERATURE_ENTITY_ID)
            ),
            humidity_entity_id=_normalize_entity_id(data.get(CONF_HUMIDITY_ENTITY_ID)),
            co2_entity_id=_normalize_entity_id(data.get(CONF_CO2_ENTITY_ID)),
            button_configs=button_configs,
        )

    @property
    def has_supply(self) -> bool:
        """Return true if the zone has at least one supply damper."""
        return bool(self.supply_damper_ids)

    @property
    def has_exhaust(self) -> bool:
        """Return true if the zone has at least one exhaust damper."""
        return bool(self.exhaust_damper_ids)

    @property
    def enabled_button_configs(self) -> tuple[ZoneButtonConfig, ...]:
        """Return enabled button configs for this zone."""
        return tuple(button for button in self.button_configs if button.enabled)

    def as_dict(self) -> dict[str, Any]:
        """Return zone config as serializable dictionary."""
        return {
            CONF_ZONE_INDEX: self.zone_index,
            CONF_ZONE_ENABLED: self.enabled,
            CONF_ZONE_NAME: self.zone_name,
            CONF_AREA_ID: self.area_id,
            CONF_SUPPLY_DAMPER_IDS: list(self.supply_damper_ids),
            CONF_EXHAUST_DAMPER_IDS: list(self.exhaust_damper_ids),
            CONF_BUTTON_IDS: list(self.button_ids),
            CONF_ALFA_INDEX: self.alfa_index,
            CONF_WRITEBACK_ENABLED: self.writeback_enabled,
            CONF_TEMPERATURE_ENTITY_ID: self.temperature_entity_id,
            CONF_HUMIDITY_ENTITY_ID: self.humidity_entity_id,
            CONF_CO2_ENTITY_ID: self.co2_entity_id,
            CONF_BUTTON_CONFIGS: [
                button_config.as_dict() for button_config in self.button_configs
            ],
        }


def load_slot_configs(options: dict[str, Any]) -> list[ExternalSensorSlotConfig]:
    """Load all slot configs from config entry options."""
    serialized = options.get(CONF_EXTERNAL_SENSOR_SLOTS, [])
    return [
        ExternalSensorSlotConfig.from_mapping(
            index, _safe_slot_mapping(serialized, index)
        )
        for index in range(1, SLOT_COUNT + 1)
    ]


def dump_slot_configs(
    slot_configs: list[ExternalSensorSlotConfig],
) -> list[dict[str, Any]]:
    """Serialize slot configs for config entry options."""
    return [slot_config.as_dict() for slot_config in slot_configs]


def load_zone_configs(options: dict[str, Any]) -> list[ZoneConfig]:
    """Load all zone configs from config entry options."""
    serialized = options.get(CONF_ZONE_CONFIGS, [])
    return [
        ZoneConfig.from_mapping(index, _safe_index_mapping(serialized, index))
        for index in range(1, SLOT_COUNT + 1)
    ]


def dump_zone_configs(zone_configs: list[ZoneConfig]) -> list[dict[str, Any]]:
    """Serialize zone configs for config entry options."""
    return [zone_config.as_dict() for zone_config in zone_configs]


def zone_setup_defaults() -> dict[str, Any]:
    """Return default zone-oriented setup options."""
    return {
        CONF_EXTERNAL_SENSOR_MODE: DEFAULT_EXTERNAL_SENSOR_MODE,
        CONF_WRITE_INTERVAL_MS: DEFAULT_WRITE_INTERVAL_MS,
        CONF_EXTERNAL_BUTTONS_ENABLED: DEFAULT_EXTERNAL_BUTTONS_ENABLED,
        CONF_ZONE_CONFIGS: [
            ZoneConfig(zone_index=index).as_dict() for index in range(1, SLOT_COUNT + 1)
        ],
    }


def derive_slot_configs_from_zone_options(
    options: dict[str, Any],
) -> list[ExternalSensorSlotConfig]:
    """Map zone write-back config onto the ext_sens slot runtime model."""
    zone_configs = load_zone_configs(options)
    sensor_mode = str(
        options.get(CONF_EXTERNAL_SENSOR_MODE, DEFAULT_EXTERNAL_SENSOR_MODE)
    )
    return [
        ExternalSensorSlotConfig(
            slot_index=zone_config.zone_index,
            enabled=(
                zone_config.enabled
                and sensor_mode == EXTERNAL_SENSOR_MODE_HA_WRITEBACK
                and zone_config.has_supply
                and zone_config.writeback_enabled
            ),
            slot_name=zone_config.zone_name,
            temperature_entity_id=zone_config.temperature_entity_id,
            humidity_entity_id=zone_config.humidity_entity_id,
            co2_entity_id=zone_config.co2_entity_id,
            floor_temperature_entity_id=None,
        )
        for zone_config in zone_configs
    ]


def has_zone_config(options: dict[str, Any]) -> bool:
    """Return true when the entry uses the new zone-oriented config model."""
    return CONF_ZONE_CONFIGS in options


def derive_bridge_update_interval_s(options: dict[str, Any] | None) -> int:
    """Return the effective bridge cadence for the current config model."""
    if options is None:
        return DEFAULT_BRIDGE_UPDATE_INTERVAL_S

    if has_zone_config(options):
        write_interval_ms = int(
            options.get(CONF_WRITE_INTERVAL_MS, DEFAULT_WRITE_INTERVAL_MS)
        )
        return max(1, (write_interval_ms + 999) // 1000)

    return int(
        options.get(CONF_BRIDGE_UPDATE_INTERVAL_S, DEFAULT_BRIDGE_UPDATE_INTERVAL_S)
    )


def default_options() -> dict[str, Any]:
    """Return default options payload for new config entries."""
    bridge_options = BridgeOptions()
    options = {
        **bridge_options.as_dict(),
        **zone_setup_defaults(),
        CONF_EXTERNAL_SENSOR_SLOTS: [
            ExternalSensorSlotConfig(slot_index=index).as_dict()
            for index in range(1, SLOT_COUNT + 1)
        ],
    }
    options[CONF_BRIDGE_UPDATE_INTERVAL_S] = derive_bridge_update_interval_s(options)
    return options


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
class ButtonActivationState:
    """Runtime diagnostics state for one exposed external button."""

    zone_index: int
    button_index: int
    slot_index: int | None = None
    button_mode: str = BUTTON_MODE_BOOST
    max_active_seconds: int = DEFAULT_BUTTON_MAX_ACTIVE_SECONDS
    last_attempt_at: datetime | None = None
    last_completed_at: datetime | None = None
    last_result: str | None = None
    last_reason: str | None = None
    last_error: str | None = None
    last_source: str | None = None
    last_requested_duration_seconds: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return runtime state as serializable diagnostics payload."""
        return {
            "zone_index": self.zone_index,
            "button_index": self.button_index,
            "slot_index": self.slot_index,
            "button_mode": self.button_mode,
            "max_active_seconds": self.max_active_seconds,
            "last_attempt_at": self.last_attempt_at.isoformat()
            if self.last_attempt_at
            else None,
            "last_completed_at": self.last_completed_at.isoformat()
            if self.last_completed_at
            else None,
            "last_result": self.last_result,
            "last_reason": self.last_reason,
            "last_error": self.last_error,
            "last_source": self.last_source,
            "last_requested_duration_seconds": self.last_requested_duration_seconds,
        }


@dataclass(slots=True)
class FuturaRuntimeData:
    """Runtime objects held on ConfigEntry.runtime_data."""

    coordinator: "FuturaCoordinator"
    bridge: "ExternalSensorBridge"
    transition_state: str = "active"
    suppress_reload: bool = False
    cleanup_complete: bool = False
    alfa_discovery: Any = None
    sensor_visibility: Any = None
    button_visibility: Any = None


def eligible_button_members(config: dict[str, Any], slot: int) -> tuple[str, ...]:
    """Committed configuration defines relevance independently of runtime state."""
    row = config["button_slots"][str(slot)]
    if not row["enabled"] or row["ownership"] == "none":
        return ()
    if row["ownership"] == "ha_control":
        return ("active", "timer", "action")
    return ("active", "timer")


FuturaConfigEntry: TypeAlias = ConfigEntry[FuturaRuntimeData]


def _normalize_entity_id(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _normalize_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _normalize_int_tuple(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(int(item) for item in value)


def _normalize_damper_name_tuple(value: Any) -> tuple[tuple[int, str], ...]:
    if not isinstance(value, Mapping):
        return ()
    normalized: list[tuple[int, str]] = []
    for raw_key, raw_name in value.items():
        try:
            damper_index = int(raw_key)
        except (TypeError, ValueError):
            continue
        name = str(raw_name).strip()
        if not name:
            continue
        normalized.append((damper_index, name))
    normalized.sort(key=lambda item: item[0])
    return tuple(normalized)


def _safe_slot_mapping(serialized: Any, slot_index: int) -> dict[str, Any] | None:
    return _safe_index_mapping(serialized, slot_index)


def _safe_index_mapping(serialized: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(serialized, list):
        return None
    if len(serialized) < index:
        return None
    data = serialized[index - 1]
    return data if isinstance(data, dict) else None


# ---------- v2 zone config helpers ----------


CONF_V2_ZONES: str = "v2_zones"


def all_zone_keys() -> list[str]:
    """Return all 16 zone keys in canonical order."""
    keys: list[str] = []
    for i in range(1, ZONE_COUNT + 1):
        keys.append(f"supply_{i}")
    for i in range(1, ZONE_COUNT + 1):
        keys.append(f"exhaust_{i}")
    return keys


def load_v2_zone_configs(options: dict[str, Any]) -> dict[str, ZoneV2Config]:
    """Load all v2 zone configs from config entry options."""
    raw = options.get(CONF_V2_ZONES, {})
    result: dict[str, ZoneV2Config] = {}
    for key in all_zone_keys():
        result[key] = ZoneV2Config.from_mapping(key, raw.get(key))
    return result


def dump_v2_zone_configs(configs: dict[str, ZoneV2Config]) -> dict[str, Any]:
    """Serialize v2 zone configs for config entry options."""
    return {key: config.as_dict() for key, config in configs.items()}


def has_v2_zone_config(options: dict[str, Any]) -> bool:
    """Return true when the entry uses v2 zone-oriented config model."""
    return CONF_V2_ZONES in options


def v2_zone_setup_defaults() -> dict[str, Any]:
    """Return default v2 zone-oriented setup options."""
    return {
        CONF_V2_ZONES: {},
        CONF_VARIOBREEZE: False,
        CONF_READ_INTERVAL_MS: DEFAULT_READ_INTERVAL_MS,
        CONF_WRITE_INTERVAL_MS: DEFAULT_WRITE_INTERVAL_MS,
    }


def derive_slot_configs_from_v2_zones(
    options: dict[str, Any],
) -> list[ExternalSensorSlotConfig]:
    """Map v2 per-zone write-back config onto the ext_sens slot runtime model."""
    zones = load_v2_zone_configs(options)
    result: list[ExternalSensorSlotConfig] = []
    for i in range(1, ZONE_COUNT + 1):
        key = f"supply_{i}"
        zone = zones.get(key)
        if zone is None:
            result.append(ExternalSensorSlotConfig(slot_index=i))
            continue
        writeback_active = zone.enabled and zone.sensor_mode == SENSOR_MODE_HA_WRITEBACK
        result.append(
            ExternalSensorSlotConfig(
                slot_index=i,
                enabled=writeback_active,
                slot_name=zone.name,
                temperature_entity_id=zone.temperature_entity_id,
                humidity_entity_id=zone.humidity_entity_id,
                co2_entity_id=zone.co2_entity_id,
                floor_temperature_entity_id=zone.floor_temperature_entity_id,
            )
        )
    return result


def derive_bridge_update_interval_s_v2(options: dict[str, Any]) -> int:
    """Return the effective bridge cadence for v2 config model."""
    write_interval_ms = int(
        options.get(CONF_WRITE_INTERVAL_MS, DEFAULT_WRITE_INTERVAL_MS)
    )
    return max(1, (write_interval_ms + 999) // 1000)


def migrate_v1_to_v2(
    data: dict[str, Any], options: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Migrate v1 config entry to v2 schema. Returns (new_data, new_options)."""
    import logging

    _LOGGER = logging.getLogger(__name__)

    new_data = dict(data)
    new_options = dict(options)

    # Detect VarioBreeze from fut_config if available, otherwise from zone presence
    variobreeze = bool(options.get(CONF_ZONE_CONFIGS))

    v1_zones = load_zone_configs(options) if CONF_ZONE_CONFIGS in options else []
    v1_sensor_mode = str(
        options.get(CONF_EXTERNAL_SENSOR_MODE, DEFAULT_EXTERNAL_SENSOR_MODE)
    )
    v1_buttons_enabled = bool(options.get(CONF_EXTERNAL_BUTTONS_ENABLED, False))
    v1_write_interval = int(
        options.get(CONF_WRITE_INTERVAL_MS, DEFAULT_WRITE_INTERVAL_MS)
    )

    v2_zones: dict[str, dict[str, Any]] = {}

    for v1_zone in v1_zones:
        idx = v1_zone.zone_index
        has_saved_metadata = _v1_zone_has_saved_metadata(v1_zone)
        has_supply_config = _v1_zone_has_supply_config(v1_zone)
        has_exhaust_config = _v1_zone_has_exhaust_config(v1_zone)

        # Map supply zone
        if has_supply_config or (has_saved_metadata and not has_exhaust_config):
            supply_key = f"supply_{idx}"
            sensor_mode = SENSOR_MODE_NONE
            if (
                v1_sensor_mode == EXTERNAL_SENSOR_MODE_HA_WRITEBACK
                and v1_zone.writeback_enabled
            ):
                sensor_mode = SENSOR_MODE_HA_WRITEBACK
            elif v1_sensor_mode == EXTERNAL_SENSOR_MODE_OBSERVE_ONLY:
                sensor_mode = SENSOR_MODE_READ if v1_zone.enabled else SENSOR_MODE_NONE

            v2_zones[supply_key] = {
                CONF_ZONE_ENABLED: v1_zone.enabled,
                CONF_ZONE_NAME: v1_zone.zone_name,
                CONF_ZONE_TYPE: "supply",
                CONF_ZONE_INDEX: idx,
                CONF_AREA_ID: v1_zone.area_id,
                CONF_SENSOR_MODE: sensor_mode,
                CONF_TEMPERATURE_ENTITY_ID: v1_zone.temperature_entity_id,
                CONF_HUMIDITY_ENTITY_ID: v1_zone.humidity_entity_id,
                CONF_CO2_ENTITY_ID: v1_zone.co2_entity_id,
                CONF_FLOOR_TEMPERATURE_ENTITY_ID: None,
                CONF_EXT_BUTTON_MODE: EXT_BUTTON_MODE_NONE,
                CONF_BUTTON_MODE: BUTTON_MODE_BOOST,
                CONF_DEFAULT_TIMER_SECONDS: DEFAULT_BUTTON_MAX_ACTIVE_SECONDS,
            }

        # Map exhaust zone
        if has_exhaust_config or (has_saved_metadata and not has_supply_config):
            exhaust_key = f"exhaust_{idx}"
            ext_btn_mode = EXT_BUTTON_MODE_NONE
            btn_type = BUTTON_MODE_BOOST
            btn_timer = DEFAULT_BUTTON_MAX_ACTIVE_SECONDS
            if v1_buttons_enabled and v1_zone.enabled_button_configs:
                first_btn = v1_zone.enabled_button_configs[0]
                ext_btn_mode = EXT_BUTTON_MODE_HA_CONTROL
                btn_type = first_btn.button_mode
                btn_timer = first_btn.max_active_seconds

            v2_zones[exhaust_key] = {
                CONF_ZONE_ENABLED: v1_zone.enabled,
                CONF_ZONE_NAME: v1_zone.zone_name,
                CONF_ZONE_TYPE: "exhaust",
                CONF_ZONE_INDEX: idx,
                CONF_AREA_ID: v1_zone.area_id,
                CONF_SENSOR_MODE: SENSOR_MODE_NONE,
                CONF_TEMPERATURE_ENTITY_ID: None,
                CONF_HUMIDITY_ENTITY_ID: None,
                CONF_CO2_ENTITY_ID: None,
                CONF_FLOOR_TEMPERATURE_ENTITY_ID: None,
                CONF_EXT_BUTTON_MODE: ext_btn_mode,
                CONF_BUTTON_MODE: btn_type,
                CONF_DEFAULT_TIMER_SECONDS: btn_timer,
            }

    new_options[CONF_V2_ZONES] = v2_zones
    new_options[CONF_VARIOBREEZE] = variobreeze
    new_options[CONF_READ_INTERVAL_MS] = DEFAULT_READ_INTERVAL_MS
    if CONF_WRITE_INTERVAL_MS not in new_options:
        new_options[CONF_WRITE_INTERVAL_MS] = v1_write_interval

    _LOGGER.info(
        "Migrated config entry from v1 to v2: %d v1 zones -> %d v2 zone keys",
        len(v1_zones),
        len(v2_zones),
    )

    return new_data, new_options


def _v1_zone_has_saved_metadata(zone: ZoneConfig) -> bool:
    """Return true when the v1 zone carries user-entered config worth preserving."""
    return bool(zone.enabled or zone.zone_name or zone.area_id)


def _v1_zone_has_supply_config(zone: ZoneConfig) -> bool:
    """Return true when the v1 zone contains supply-side state or bindings."""
    return bool(
        zone.supply_damper_ids
        or zone.alfa_index is not None
        or zone.writeback_enabled
        or zone.temperature_entity_id
        or zone.humidity_entity_id
        or zone.co2_entity_id
    )


def _v1_zone_has_exhaust_config(zone: ZoneConfig) -> bool:
    """Return true when the v1 zone contains exhaust-side state or bindings."""
    return bool(
        zone.exhaust_damper_ids or zone.button_ids or zone.enabled_button_configs
    )


# Canonical v3 configuration. Legacy classes above are migration-only adapters.
def default_v3_options() -> dict[str, Any]:
    """Return a complete independent canonical configuration."""
    return {
        "zones": {
            key: {
                "enabled": False,
                "name": "",
                "area_id": None,
                "supply_damper_ids": [],
                "exhaust_damper_ids": [],
                "damper_names": {},
                "alfa_index": None,
                "button_ids": [],
            }
            for key in all_zone_keys()
        },
        "sensor_slots": {
            str(i): {
                "enabled": False,
                "mode": "none",
                "name": "",
                "zone_binding": None,
                **{
                    key: None
                    for key in (
                        "temperature_entity_id",
                        "humidity_entity_id",
                        "co2_entity_id",
                        "floor_temperature_entity_id",
                    )
                },
                "unitless_assumptions": {
                    metric: None
                    for metric in (
                        "temperature",
                        "humidity",
                        "co2",
                        "floor_temperature",
                    )
                },
            }
            for i in range(1, 9)
        },
        "button_slots": {
            str(i): {
                "enabled": False,
                "ownership": "none",
                "name": "",
                "zone_binding": None,
                "button_mode": "boost",
                "default_timer_seconds": 180,
                "max_active_seconds": 10800,
                "entity_identity_suffix": f"external_button_{i}",
            }
            for i in range(1, 9)
        },
        "runtime": {
            "bridge_enabled": True,
            "read_interval_ms": 10000,
            "write_interval_ms": 12000,
            "scan_interval_s": 5,
            "stale_after_s": DEFAULT_STALE_AFTER_S,
            "write_on_change_only": True,
            "force_resync_every_s": 300,
            "log_level_bridge": "normal",
        },
        "variobreeze": False,
        "migration_needs_repair": False,
    }


def validate_v3_options(options: Mapping[str, Any]) -> dict[str, str]:
    """Validate canonical shape and values without coercion or legacy fallbacks."""
    from .validation import METRIC_TARGET_UNITS, validate_runtime_options

    errors: dict[str, str] = {}
    runtime = options.get("runtime")
    if not isinstance(runtime, Mapping):
        errors["runtime"] = "invalid_container"
    else:
        errors.update(
            {
                f"runtime.{key}": value
                for key, value in validate_runtime_options(runtime).items()
            }
        )
    for group, keys in (
        ("zones", set(all_zone_keys())),
        ("sensor_slots", {str(i) for i in range(1, 9)}),
        ("button_slots", {str(i) for i in range(1, 9)}),
    ):
        rows = options.get(group)
        if not isinstance(rows, Mapping) or set(rows) != keys:
            errors[group] = "invalid_slots"
            continue
        suffixes: set[str] = set()
        for index, row in rows.items():
            prefix = f"{group}.{index}"
            if not isinstance(row, Mapping):
                errors[prefix] = "invalid_container"
                continue
            if type(row.get("enabled")) is not bool:
                errors[f"{prefix}.enabled"] = "invalid_boolean"
            if not isinstance(row.get("name"), str):
                errors[f"{prefix}.name"] = "invalid_name"
            if group == "zones":
                continue
            zone = row.get("zone_binding")
            side = "supply" if group == "sensor_slots" else "exhaust"
            if zone is not None and (
                not isinstance(zone, str)
                or zone not in {f"{side}_{i}" for i in range(1, 9)}
            ):
                errors[f"{prefix}.zone_binding"] = "invalid_zone"
            if group == "sensor_slots":
                if row.get("mode") not in ("none", "read", "ha_writeback"):
                    errors[f"{prefix}.mode"] = "invalid_sensor_mode"
                sources = [
                    row.get(f"{metric}_entity_id") for metric in METRIC_TARGET_UNITS
                ]
                if (
                    row.get("enabled")
                    and row.get("mode") == "ha_writeback"
                    and not any(sources)
                ):
                    errors[f"{prefix}.mode"] = "writeback_entities_required"
                for metric in METRIC_TARGET_UNITS:
                    source = row.get(f"{metric}_entity_id")
                    if source is not None and (
                        not isinstance(source, str)
                        or source.partition(".")[0]
                        not in ("sensor", "number", "input_number")
                        or not source.partition(".")[2]
                    ):
                        errors[f"{prefix}.{metric}_entity_id"] = "invalid_source"
                assumptions = row.get("unitless_assumptions", {})
                if not isinstance(assumptions, Mapping):
                    errors[f"{prefix}.unitless_assumptions"] = "invalid_unit"
                else:
                    for metric, unit in assumptions.items():
                        if metric not in METRIC_TARGET_UNITS or unit not in (
                            None,
                            METRIC_TARGET_UNITS.get(metric),
                        ):
                            errors[f"{prefix}.unitless_assumptions"] = "invalid_unit"
            else:
                if row.get("ownership") not in ("none", "futura", "ha_control"):
                    errors[f"{prefix}.ownership"] = "invalid_button_mode"
                if row.get("button_mode") not in ("boost", "digestor"):
                    errors[f"{prefix}.button_mode"] = "invalid_button_mode"
                maximum, duration = (
                    row.get("max_active_seconds"),
                    row.get("default_timer_seconds"),
                )
                if type(maximum) is not int or not 1 <= maximum <= 10800:
                    errors[f"{prefix}.max_active_seconds"] = "invalid_duration"
                if (
                    type(duration) is not int
                    or type(maximum) is not int
                    or not 1 <= duration <= maximum
                ):
                    errors[f"{prefix}.default_timer_seconds"] = "invalid_duration"
                suffix = row.get("entity_identity_suffix")
                if not isinstance(suffix, str) or not suffix or suffix in suffixes:
                    errors[f"{prefix}.entity_identity_suffix"] = "duplicate_identity"
                suffixes.add(str(suffix))
    for key in ("variobreeze", "migration_needs_repair"):
        if type(options.get(key, False)) is not bool:
            errors[key] = "invalid_boolean"
    recovery = options.get("button_recovery_requests", [])
    if not isinstance(recovery, list) or any(
        not isinstance(slot, str) or slot not in {str(i) for i in range(1, 9)}
        for slot in recovery
    ):
        errors["button_recovery_requests"] = "invalid_slot"
    return errors


def with_source_age_default(options: Mapping[str, Any]) -> dict[str, Any]:
    """Copy options and fill only an absent source-age limit in runtime."""
    from copy import deepcopy

    result = deepcopy(dict(options))
    if isinstance(runtime := result.get("runtime"), dict):
        runtime.setdefault(CONF_STALE_AFTER_S, DEFAULT_STALE_AFTER_S)
    return result


def load_v3_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """Read canonical options; invalid explicit saved state requires repair."""
    result = with_source_age_default(options)
    errors = validate_v3_options(result)
    if errors:
        raise ValueError("invalid_v3_configuration", errors)
    return result


def v3_sensor_configs(options: Mapping[str, Any]) -> list[ExternalSensorSlotConfig]:
    """Adapt canonical writer slots without consulting legacy projections."""
    config = load_v3_options(options)
    return [
        ExternalSensorSlotConfig(
            slot_index=int(index),
            enabled=row["enabled"]
            and row["mode"] == "ha_writeback"
            and config["runtime"]["bridge_enabled"]
            and not config.get("migration_needs_repair"),
            slot_name=row["name"],
            **{
                key: row.get(key)
                for key in (
                    "temperature_entity_id",
                    "humidity_entity_id",
                    "co2_entity_id",
                    "floor_temperature_entity_id",
                )
            },
        )
        for index, row in config["sensor_slots"].items()
    ]


def migrate_to_v3(
    data: dict[str, Any],
    options: dict[str, Any],
    version: int,
    unique_id: str | None = None,
    entry_id: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Migrate from the untouched legacy snapshot, preserving every raw choice."""
    from .migration import migrate_configuration

    return migrate_configuration(data, options, version, unique_id, entry_id)
