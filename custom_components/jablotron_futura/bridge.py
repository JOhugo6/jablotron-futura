"""Bridge runtime that maps Home Assistant entities to ext_sens_* Modbus slots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import asyncio
import time
from typing import Any

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    METRIC_CO2,
    METRIC_FLOOR_TEMPERATURE,
    METRIC_HUMIDITY,
    METRIC_TEMPERATURE,
    METRIC_TO_ENTITY_KEY,
    METRIC_TO_INVALID_BIT,
)
from .coordinator import FuturaCoordinator
from .models import (
    BridgeOptions,
    ExternalSensorSlotConfig,
    FuturaConfigEntry,
    SlotRuntimeState,
    load_v3_options,
    v3_sensor_configs,
)
from .validation import normalize_metric_value

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
            self.temperature_raw & 0xFFFF,
            self.humidity_raw,
            self.co2_raw,
            self.floor_temperature_raw & 0xFFFF,
        ]


class ExternalSensorBridge:
    """One coalescing writer; canonical options only and no stale snapshots."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: FuturaConfigEntry,
        coordinator: FuturaCoordinator,
    ) -> None:
        self.hass, self.entry, self.coordinator = hass, entry, coordinator
        self.config = load_v3_options(dict(entry.options))
        runtime = self.config["runtime"]
        self.options = BridgeOptions.from_mapping(runtime)
        self.interval = runtime["write_interval_ms"] / 1000
        self.slot_configs = v3_sensor_configs(self.config)
        self.slot_states = {
            slot: SlotRuntimeState(slot_index=slot) for slot in range(1, 9)
        }
        self._dirty_slots = set(range(1, 9))
        self._resync_slots = set(range(1, 9))
        self._owned: set[int] = set()
        self._attempts: dict[int, float] = {}
        self._successes: dict[int, float] = {}
        self._generation = 0
        self._frozen = False
        self._task = None
        self._listener_remove = []
        self._seen_reconnect_generation = coordinator.reconnect_generation
        self._worker_lock = asyncio.Lock()

    async def async_start(self) -> None:
        self._frozen = False
        ids = sorted(
            {entity for config in self.slot_configs for entity in config.entity_ids()}
        )
        if ids:
            self._listener_remove.append(
                async_track_state_change_event(
                    self.hass, ids, self._handle_source_state_change
                )
            )
        await self.async_process_pending("startup")
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while not self._frozen:
            await asyncio.sleep(min(1, self.interval))
            await self.async_process_pending("timer")

    @callback
    def _handle_source_state_change(self, event: Any) -> None:
        for config in self.slot_configs:
            if event.data["entity_id"] in config.entity_ids():
                self._dirty_slots.add(config.slot_index)

    async def async_freeze(self) -> None:
        self._frozen = True
        self._generation += 1
        for remove in self._listener_remove:
            remove()
        self._listener_remove.clear()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        async with self._worker_lock:
            pass

    async def async_resume(self) -> None:
        self._dirty_slots.update(range(1, 9))
        self._resync_slots.update(range(1, 9))
        await self.async_start()

    async def async_stop(self, clear: bool = True) -> None:
        await self.async_freeze()
        if not clear or self.config.get("migration_needs_repair"):
            return
        pending = sorted(self._owned)
        self._owned.clear()  # one attempt even if caller cancels or unload retries
        for index, slot in enumerate(pending):
            result = "ok"
            try:
                await self.coordinator.async_write_external_sensor_block(
                    slot, [0] * 6, cleanup=True
                )
            except asyncio.CancelledError:
                for skipped in pending[index:]:
                    await self.coordinator.async_record_clear(
                        {
                            "kind": "sensor",
                            "slot": skipped,
                            "generation": self._generation,
                            "result": "skipped_timeout",
                            "error_code": "deadline",
                        }
                    )
                raise
            except Exception:
                result = "failed"
            await self.coordinator.async_record_clear(
                {
                    "kind": "sensor",
                    "slot": slot,
                    "generation": self._generation,
                    "result": result,
                    "error_code": None if result == "ok" else "clear_failed",
                }
            )

    def diagnostics_snapshot(self) -> dict[str, Any]:
        return {
            "runtime": self.config["runtime"],
            "slots": self.config["sensor_slots"],
            "slot_states": {
                str(slot): state.as_dict() for slot, state in self.slot_states.items()
            },
            "owned": sorted(self._owned),
            "generation": self._generation,
        }

    def _slot_write_enabled(self, config: ExternalSensorSlotConfig) -> bool:
        return bool(
            not self._frozen
            and not self.config.get("migration_needs_repair")
            and self.options.bridge_enabled
            and config.enabled
        )

    async def async_process_pending(self, trigger_reason: str) -> None:
        if self._frozen or self._worker_lock.locked():
            return
        async with self._worker_lock:
            generation = self._generation
            reconnect = (
                self._seen_reconnect_generation != self.coordinator.reconnect_generation
            )
            self._seen_reconnect_generation = self.coordinator.reconnect_generation
            if reconnect:
                self._dirty_slots.update(range(1, 9))
                self._resync_slots.update(range(1, 9))
            for config in self.slot_configs:
                slot = config.slot_index
                if generation != self._generation or not self._slot_write_enabled(
                    config
                ):
                    self._dirty_slots.discard(slot)
                    continue
                now = dt_util.utcnow()
                monotonic = time.monotonic()
                state = self.slot_states[slot]
                payload = build_slot_payload(
                    config,
                    self.options,
                    now,
                    self.hass,
                    self.config["sensor_slots"][str(slot)]["unitless_assumptions"],
                )
                state.source_snapshot = payload.source_snapshot
                # Recompute every tick: freshness can change without any HA event.
                due = (
                    monotonic - self._attempts.get(slot, float("-inf")) >= self.interval
                )
                force = (
                    slot in self._resync_slots
                    or monotonic - self._successes.get(slot, float("-inf"))
                    >= self.options.force_resync_every_s
                )
                changed = payload.registers != state.last_payload
                if not due or not (
                    changed
                    or force
                    or reconnect
                    or slot in self._dirty_slots
                    or not self.options.write_on_change_only
                ):
                    continue
                if (
                    not changed
                    and self.options.write_on_change_only
                    and not force
                    and not reconnect
                    and state.last_error is None
                ):
                    self._dirty_slots.discard(slot)
                    continue
                self._attempts[slot] = monotonic
                state.last_attempt_at = now
                state.last_reason = trigger_reason
                self._owned.add(slot)
                try:
                    await self.coordinator.async_write_external_sensor_block(
                        slot, payload.registers
                    )
                except Exception:
                    state.last_error = "write_failed"
                    self._dirty_slots.add(slot)
                    continue
                state.last_payload = payload.registers
                state.last_successful_write_at = now
                state.last_error = None
                state.present, state.invalidate_mask = (
                    payload.present,
                    payload.invalidate_mask,
                )
                state.temperature_raw, state.humidity_raw = (
                    payload.temperature_raw,
                    payload.humidity_raw,
                )
                state.co2_raw, state.floor_temperature_raw = (
                    payload.co2_raw,
                    payload.floor_temperature_raw,
                )
                self._successes[slot] = time.monotonic()
                self._resync_slots.discard(slot)
                state.pending_write_reason = None
                self._dirty_slots.discard(slot)


def build_slot_payload(
    slot_config: ExternalSensorSlotConfig,
    options: BridgeOptions,
    now: datetime,
    hass: HomeAssistant,
    assumptions: dict[str, str | None] | None = None,
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
        result = _normalize_metric(
            metric, state, options, now, (assumptions or {}).get(metric)
        )
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
    assumption: str | None = None,
) -> _MetricResult:
    if state is None:
        return _MetricResult(None, {"status": "missing"})
    if state.state.lower() in UNKNOWN_STATES:
        return _MetricResult(None, {"status": state.state.lower()})
    reported = getattr(state, "last_reported", state.last_updated)
    try:
        age = now - reported
    except (TypeError, ValueError, OverflowError):
        return _MetricResult(None, {"status": "invalid_timestamp"})
    if age > timedelta(seconds=options.stale_after_s):
        return _MetricResult(
            None, {"status": "stale", "last_reported": reported.isoformat()}
        )
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    normalized = normalize_metric_value(metric, state.state, unit, assumption)
    if normalized is None:
        return _MetricResult(None, {"status": "invalid", "unit": unit})
    scale = 10 if metric in (METRIC_TEMPERATURE, METRIC_FLOOR_TEMPERATURE) else 1
    return _MetricResult(
        int(round(normalized * scale)),
        {"status": "ok", "value": normalized, "unit": unit},
    )
