"""Bridge runtime that maps Home Assistant entities to ext_sens_* Modbus slots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CO2_ENTITY_ID,
    CONF_ENABLED,
    CONF_FLOOR_TEMPERATURE_ENTITY_ID,
    CONF_HUMIDITY_ENTITY_ID,
    CONF_SLOT_NAME,
    CONF_TEMPERATURE_ENTITY_ID,
    LOG_LEVEL_DEBUG,
    METRIC_CO2,
    METRIC_FLOOR_TEMPERATURE,
    METRIC_HUMIDITY,
    METRIC_TEMPERATURE,
    METRIC_TO_ENTITY_KEY,
    METRIC_TO_INVALID_BIT,
    SLOT_COUNT,
)
from .coordinator import FuturaCoordinator
from .models import BridgeOptions, ExternalSensorSlotConfig, FuturaConfigEntry, SlotRuntimeState, load_slot_configs

_LOGGER = logging.getLogger(__name__)

UNKNOWN_STATES = {"unknown", "unavailable", "none", ""}
CELSIUS_UNITS = {"°C", "C", "degC"}
FAHRENHEIT_UNITS = {"°F", "degF"}


@dataclass(slots=True, frozen=True)
class SlotPayload:
    """Normalized payload for one external sensor slot."""

    slot_index: int
    present: int
    invalidate_mask: int
    temperature_raw: int
    humidity_raw: int
    co2_raw: int
    floor_temperature_raw: int
    source_snapshot: dict[str, Any] = field(default_factory=dict)
    unitless_entities: tuple[tuple[str, str], ...] = ()

    @property
    def registers(self) -> list[int]:
        """Return registers in ext_sens slot order."""
        return [
            self.present,
            self.invalidate_mask,
            self.temperature_raw,
            self.humidity_raw,
            self.co2_raw,
            self.floor_temperature_raw,
        ]


class ExternalSensorBridge:
    """Runtime bridge from HA entity states to Modbus ext_sens_* writes."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: FuturaConfigEntry,
        coordinator: FuturaCoordinator,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.options = BridgeOptions.from_mapping(dict(entry.options))
        self.slot_configs = load_slot_configs(dict(entry.options))
        self.slot_states = {
            slot_index: SlotRuntimeState(slot_index=slot_index)
            for slot_index in range(1, SLOT_COUNT + 1)
        }
        self._dirty_slots = set(range(1, SLOT_COUNT + 1))
        self._unitless_warned_entities: set[tuple[str, str]] = set()
        self._listener_remove: list[callable] = []
        self._timer_remove = None
        self._coordinator_listener_remove = None
        self._seen_reconnect_generation = coordinator.reconnect_generation

    async def async_start(self) -> None:
        """Start bridge listeners."""
        self._subscribe_entity_listeners()
        self._coordinator_listener_remove = self.coordinator.async_add_listener(
            self._handle_coordinator_update
        )
        self._timer_remove = async_track_time_interval(
            self.hass,
            self._handle_timer,
            timedelta(seconds=self.options.bridge_update_interval_s),
        )
        await self.async_process_pending("startup")

    async def async_stop(self) -> None:
        """Stop bridge listeners."""
        for remove in self._listener_remove:
            remove()
        self._listener_remove.clear()

        if self._coordinator_listener_remove:
            self._coordinator_listener_remove()
            self._coordinator_listener_remove = None

        if self._timer_remove:
            self._timer_remove()
            self._timer_remove = None

    def diagnostics_snapshot(self) -> dict[str, Any]:
        """Return bridge diagnostics snapshot."""
        warnings: list[str] = [
            "This integration does not replace MyCOMPANY commissioning.",
            "Analog IN1/IN2 control may override CO2-driven behavior.",
        ]
        if self.coordinator.data.get("emergency_shutdown_active"):
            warnings.append("Emergency shutdown warning is active.")

        return {
            "bridge_options": self.options.as_dict(),
            "slot_configs": [
                {
                    "slot_index": slot_config.slot_index,
                    "enabled": slot_config.enabled,
                    "slot_name": slot_config.slot_name,
                    CONF_TEMPERATURE_ENTITY_ID: slot_config.temperature_entity_id,
                    CONF_HUMIDITY_ENTITY_ID: slot_config.humidity_entity_id,
                    CONF_CO2_ENTITY_ID: slot_config.co2_entity_id,
                    CONF_FLOOR_TEMPERATURE_ENTITY_ID: slot_config.floor_temperature_entity_id,
                }
                for slot_config in self.slot_configs
            ],
            "slot_states": {
                slot_index: runtime_state.as_dict()
                for slot_index, runtime_state in self.slot_states.items()
            },
            "operational_warnings": warnings,
            "resolved_profile": self.coordinator.profile.profile_id,
        }

    @callback
    def _handle_timer(self, _now: datetime) -> None:
        self.hass.async_create_task(self.async_process_pending("timer"))

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._sync_connection_state():
            self.hass.async_create_task(self.async_process_pending("reconnect"))

    @callback
    def _sync_connection_state(self) -> bool:
        """Track reconnects using a generation that survives missed listener windows."""
        if self._seen_reconnect_generation == self.coordinator.reconnect_generation:
            return False

        self._seen_reconnect_generation = self.coordinator.reconnect_generation
        self._mark_slots_dirty(range(1, SLOT_COUNT + 1), "reconnect")
        return True

    def _subscribe_entity_listeners(self) -> None:
        entity_ids = sorted(
            {
                entity_id
                for slot_config in self.slot_configs
                for entity_id in slot_config.entity_ids()
            }
        )
        if not entity_ids:
            return
        self._listener_remove.append(
            async_track_state_change_event(
                self.hass,
                entity_ids,
                self._handle_source_state_change,
            )
        )

    @callback
    def _handle_source_state_change(self, event: Any) -> None:
        entity_id = event.data["entity_id"]
        affected_slots = [
            slot_config.slot_index
            for slot_config in self.slot_configs
            if entity_id in slot_config.entity_ids()
        ]
        if affected_slots:
            self._mark_slots_dirty(affected_slots, "source_changed")

    def _mark_slots_dirty(self, slot_indexes: Any, reason: str) -> None:
        for slot_index in slot_indexes:
            self._dirty_slots.add(int(slot_index))
            self.slot_states[int(slot_index)].pending_write_reason = reason

    async def async_process_pending(self, trigger_reason: str) -> None:
        """Process pending or watchdog-triggered writes."""
        if self._sync_connection_state():
            trigger_reason = "reconnect"

        now = dt_util.utcnow()
        for slot_config in self.slot_configs:
            slot_index = slot_config.slot_index
            runtime_state = self.slot_states[slot_index]
            force_due = bool(
                runtime_state.last_successful_write_at
                and (
                    now - runtime_state.last_successful_write_at
                ).total_seconds()
                >= self.options.force_resync_every_s
            )
            needs_processing = (
                slot_index in self._dirty_slots
                or runtime_state.last_successful_write_at is None
                or force_due
            )
            if not needs_processing:
                continue

            if runtime_state.last_attempt_at and (
                now - runtime_state.last_attempt_at
            ).total_seconds() < self.options.bridge_update_interval_s:
                continue

            reason = runtime_state.pending_write_reason or (
                "watchdog" if force_due else trigger_reason
            )
            force_write = (
                force_due
                or reason == "reconnect"
                or runtime_state.last_error is not None
            )
            payload = build_slot_payload(
                slot_config=slot_config,
                options=self.options,
                now=now,
                hass=self.hass,
            )
            for metric, entity_id in payload.unitless_entities:
                if (metric, entity_id) not in self._unitless_warned_entities:
                    _LOGGER.warning(
                        "Slot %s uses unitless entity %s for %s; assuming target units already match Futura",
                        slot_index,
                        entity_id,
                        metric,
                    )
                    self._unitless_warned_entities.add((metric, entity_id))

            same_payload = payload.registers == runtime_state.last_payload
            if (
                same_payload
                and self.options.write_on_change_only
                and runtime_state.last_successful_write_at is not None
                and not force_write
            ):
                runtime_state.pending_write_reason = None
                runtime_state.source_snapshot = payload.source_snapshot
                self._dirty_slots.discard(slot_index)
                continue

            runtime_state.last_attempt_at = now
            runtime_state.last_reason = reason
            try:
                await self.coordinator.async_write_external_sensor_block(
                    slot_index, payload.registers
                )
            except UpdateFailed as err:
                runtime_state.last_error = str(err)
                runtime_state.pending_write_reason = reason
                _LOGGER.warning(
                    "Bridge write for slot %s failed: %s",
                    slot_index,
                    err,
                )
                continue

            runtime_state.present = payload.present
            runtime_state.invalidate_mask = payload.invalidate_mask
            runtime_state.temperature_raw = payload.temperature_raw
            runtime_state.humidity_raw = payload.humidity_raw
            runtime_state.co2_raw = payload.co2_raw
            runtime_state.floor_temperature_raw = payload.floor_temperature_raw
            runtime_state.last_payload = payload.registers
            runtime_state.last_successful_write_at = now
            runtime_state.last_error = None
            runtime_state.pending_write_reason = None
            runtime_state.source_snapshot = payload.source_snapshot
            self._dirty_slots.discard(slot_index)

            log_method = _LOGGER.debug if self.options.log_level_bridge == LOG_LEVEL_DEBUG else _LOGGER.info
            log_method(
                "Bridge wrote slot %s via profile %s to %s: %s",
                slot_index,
                self.coordinator.profile.profile_id,
                self.coordinator.profile.external_sensor_block(slot_index)[0],
                payload.registers,
            )


def build_slot_payload(
    slot_config: ExternalSensorSlotConfig,
    options: BridgeOptions,
    now: datetime,
    hass: HomeAssistant,
) -> SlotPayload:
    """Build the ext_sens payload for one slot."""
    if not options.bridge_enabled or not slot_config.enabled:
        return SlotPayload(
            slot_index=slot_config.slot_index,
            present=0,
            invalidate_mask=0,
            temperature_raw=0,
            humidity_raw=0,
            co2_raw=0,
            floor_temperature_raw=0,
            source_snapshot={},
        )

    if not slot_config.has_source():
        return SlotPayload(
            slot_index=slot_config.slot_index,
            present=0,
            invalidate_mask=0,
            temperature_raw=0,
            humidity_raw=0,
            co2_raw=0,
            floor_temperature_raw=0,
            source_snapshot={"error": "slot_enabled_without_sources"},
        )

    source_snapshot: dict[str, Any] = {}
    unitless_entities: list[tuple[str, str]] = []
    normalized_values = {
        METRIC_TEMPERATURE: 0,
        METRIC_HUMIDITY: 0,
        METRIC_CO2: 0,
        METRIC_FLOOR_TEMPERATURE: 0,
    }
    invalidate_mask = 0

    for metric, entity_key in METRIC_TO_ENTITY_KEY.items():
        entity_id = getattr(slot_config, entity_key)
        state = hass.states.get(entity_id) if entity_id else None
        result = _normalize_metric(metric, state, options, now)
        source_snapshot[metric] = result.snapshot
        if result.unitless_entity:
            unitless_entities.append((metric, result.unitless_entity))
        if result.raw_value is None:
            invalidate_mask |= 1 << METRIC_TO_INVALID_BIT[metric]
        else:
            normalized_values[metric] = result.raw_value

    return SlotPayload(
        slot_index=slot_config.slot_index,
        present=1,
        invalidate_mask=invalidate_mask,
        temperature_raw=normalized_values[METRIC_TEMPERATURE],
        humidity_raw=normalized_values[METRIC_HUMIDITY],
        co2_raw=normalized_values[METRIC_CO2],
        floor_temperature_raw=normalized_values[METRIC_FLOOR_TEMPERATURE],
        source_snapshot=source_snapshot,
        unitless_entities=tuple(unitless_entities),
    )


@dataclass(slots=True, frozen=True)
class _MetricResult:
    raw_value: int | None
    snapshot: dict[str, Any]
    unitless_entity: str | None = None


def _normalize_metric(
    metric: str,
    state: State | None,
    options: BridgeOptions,
    now: datetime,
) -> _MetricResult:
    if state is None:
        return _MetricResult(raw_value=None, snapshot={"status": "missing"})

    if state.state.lower() in UNKNOWN_STATES:
        return _MetricResult(raw_value=None, snapshot={"status": state.state.lower()})

    if now - state.last_updated > timedelta(seconds=options.stale_after_s):
        return _MetricResult(
            raw_value=None,
            snapshot={
                "status": "stale",
                "last_updated": state.last_updated.isoformat(),
            },
        )

    try:
        numeric_value = float(state.state)
    except (TypeError, ValueError):
        return _MetricResult(
            raw_value=None,
            snapshot={"status": "non_numeric", "state": state.state},
        )

    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    unitless_entity = state.entity_id if not unit else None
    if metric in (METRIC_TEMPERATURE, METRIC_FLOOR_TEMPERATURE):
        return _normalize_temperature_metric(
            numeric_value, unit, state, unitless_entity
        )
    if metric == METRIC_HUMIDITY:
        return _normalize_humidity_metric(
            numeric_value, unit, state, unitless_entity
        )
    return _normalize_co2_metric(
        numeric_value, unit, state, unitless_entity
    )


def _normalize_temperature_metric(
    value: float,
    unit: Any,
    state: State,
    unitless_entity: str | None,
) -> _MetricResult:
    normalized = value
    if unit in CELSIUS_UNITS or unit is None:
        pass
    elif unit in FAHRENHEIT_UNITS:
        normalized = (value - 32.0) * 5.0 / 9.0
    else:
        return _MetricResult(
            raw_value=None,
            snapshot={"status": "invalid_unit", "unit": unit},
        )

    if normalized < -20.0 or normalized > 100.0:
        return _MetricResult(
            raw_value=None,
            snapshot={"status": "out_of_range", "value": normalized},
        )

    return _MetricResult(
        raw_value=int(round(normalized * 10)),
        snapshot={"status": "ok", "state": state.state, "unit": unit},
        unitless_entity=unitless_entity,
    )


def _normalize_humidity_metric(
    value: float,
    unit: Any,
    state: State,
    unitless_entity: str | None,
) -> _MetricResult:
    if unit not in ("%", None):
        return _MetricResult(
            raw_value=None,
            snapshot={"status": "invalid_unit", "unit": unit},
        )
    if value < 0 or value > 100:
        return _MetricResult(
            raw_value=None,
            snapshot={"status": "out_of_range", "value": value},
        )
    return _MetricResult(
        raw_value=int(round(value)),
        snapshot={"status": "ok", "state": state.state, "unit": unit},
        unitless_entity=unitless_entity,
    )


def _normalize_co2_metric(
    value: float,
    unit: Any,
    state: State,
    unitless_entity: str | None,
) -> _MetricResult:
    if unit not in ("ppm", None):
        return _MetricResult(
            raw_value=None,
            snapshot={"status": "invalid_unit", "unit": unit},
        )
    if value < 0 or value > 10000:
        return _MetricResult(
            raw_value=None,
            snapshot={"status": "out_of_range", "value": value},
        )
    return _MetricResult(
        raw_value=int(round(value)),
        snapshot={"status": "ok", "state": state.state, "unit": unit},
        unitless_entity=unitless_entity,
    )
