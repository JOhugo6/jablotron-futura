"""Pure validation helpers used by config flow."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from .const import (
    BUTTON_MODE_BOOST,
    BUTTON_MODE_DIGESTOR,
    CONF_BRIDGE_UPDATE_INTERVAL_S,
    CONF_BUTTON_MODE,
    CONF_CO2_ENTITY_ID,
    CONF_MAX_ACTIVE_SECONDS,
    CONF_HUMIDITY_ENTITY_ID,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_WRITE_INTERVAL_MS,
    CONF_WRITEBACK_ENABLED,
    CONF_FORCE_RESYNC_EVERY_S,
    CONF_STALE_AFTER_S,
    CONF_ZONE_ENABLED,
    EXTERNAL_SENSOR_MODE_HA_WRITEBACK,
    MAX_BUTTONS_PER_ZONE,
    MAX_BUTTON_ACTIVE_SECONDS,
    MAX_DAMPERS_PER_ZONE,
    MIN_WRITE_INTERVAL_MS,
    ZONE_COUNT,
)


class _EntryLike(Protocol):
    entry_id: str
    unique_id: str | None


@dataclass(slots=True, frozen=True)
class DiscoveredZone:
    """One topology-derived candidate zone."""

    zone_index: int
    supply_damper_ids: tuple[int, ...]
    exhaust_damper_ids: tuple[int, ...]
    button_ids: tuple[int, ...]
    alfa_index: int | None
    supply_identify: bool
    exhaust_identify: bool


def has_duplicate_unique_id(
    existing_entries: Iterable[_EntryLike],
    current_entry_id: str | None,
    candidate_unique_id: str,
) -> bool:
    """Return true if another entry already uses the same unique id."""
    return any(
        entry.entry_id != current_entry_id and entry.unique_id == candidate_unique_id
        for entry in existing_entries
    )


def validate_global_options(user_input: Mapping[str, Any]) -> dict[str, str]:
    """Validate global bridge options from the options flow."""
    errors: dict[str, str] = {}
    if int(user_input[CONF_BRIDGE_UPDATE_INTERVAL_S]) < 5:
        errors[CONF_BRIDGE_UPDATE_INTERVAL_S] = "bridge_interval_too_low"
    if int(user_input[CONF_STALE_AFTER_S]) < 10:
        errors[CONF_STALE_AFTER_S] = "stale_after_too_low"
    if int(user_input[CONF_FORCE_RESYNC_EVERY_S]) < 60:
        errors[CONF_FORCE_RESYNC_EVERY_S] = "force_resync_too_low"
    return errors


def derive_discovered_zones(
    supply_bits: int,
    exhaust_bits: int,
    button_bits: int,
    alfa_bits: int,
    vzv_identify_bits: int,
) -> list[DiscoveredZone]:
    """Derive candidate zones from discovery bitmaps."""
    supply_map = _group_indexed_bits(supply_bits, group_size=4, max_groups=ZONE_COUNT)
    exhaust_map = _group_indexed_bits(exhaust_bits, group_size=4, max_groups=ZONE_COUNT)
    button_map = _group_indexed_bits(button_bits, group_size=2, max_groups=ZONE_COUNT)

    zones: list[DiscoveredZone] = []
    for zone_index in range(1, ZONE_COUNT + 1):
        supply_identify = bool(vzv_identify_bits & (1 << (zone_index - 1)))
        exhaust_identify = bool(
            vzv_identify_bits & (1 << (ZONE_COUNT + zone_index - 1))
        )
        zone = DiscoveredZone(
            zone_index=zone_index,
            supply_damper_ids=supply_map.get(zone_index, ()),
            exhaust_damper_ids=exhaust_map.get(zone_index, ()),
            button_ids=button_map.get(zone_index, ()),
            alfa_index=zone_index if alfa_bits & (1 << (zone_index - 1)) else None,
            supply_identify=supply_identify,
            exhaust_identify=exhaust_identify,
        )
        if any(
            (
                zone.supply_damper_ids,
                zone.exhaust_damper_ids,
                zone.button_ids,
                zone.alfa_index is not None,
                zone.supply_identify,
                zone.exhaust_identify,
            )
        ):
            zones.append(zone)
    return zones


def validate_discovered_zones(zones: list[DiscoveredZone]) -> dict[str, str]:
    """Validate discovered topology against MVP limits."""
    errors: dict[str, str] = {}
    if len(zones) > ZONE_COUNT:
        errors["base"] = "zone_limit_exceeded"
        return errors

    for zone in zones:
        if len(zone.supply_damper_ids) > MAX_DAMPERS_PER_ZONE:
            errors["base"] = "too_many_supply_dampers"
            return errors
        if len(zone.exhaust_damper_ids) > MAX_DAMPERS_PER_ZONE:
            errors["base"] = "too_many_exhaust_dampers"
            return errors
        if len(zone.button_ids) > MAX_BUTTONS_PER_ZONE:
            errors["base"] = "too_many_external_buttons"
            return errors
    if not any(zone.alfa_index is not None for zone in zones):
        errors["base"] = "no_alfa_detected"
    return errors


def validate_zone_writeback_options(
    sensor_mode: str,
    write_interval_ms: int,
    zone_inputs: Mapping[int, Mapping[str, Any]],
) -> dict[str, str]:
    """Validate external sensor mode and per-zone writeback settings."""
    errors: dict[str, str] = {}
    if sensor_mode != EXTERNAL_SENSOR_MODE_HA_WRITEBACK:
        return errors

    if write_interval_ms < MIN_WRITE_INTERVAL_MS:
        errors[CONF_WRITE_INTERVAL_MS] = "write_interval_too_low"

    enabled_zone_indexes = [
        zone_index
        for zone_index, values in zone_inputs.items()
        if bool(values.get(CONF_ZONE_ENABLED))
    ]
    if not enabled_zone_indexes:
        errors["base"] = "writeback_requires_supply_zone"
        return errors

    for zone_index, values in zone_inputs.items():
        if not bool(values.get("has_supply")) or not bool(
            values.get(CONF_WRITEBACK_ENABLED)
        ):
            continue
        for field_key in (
            CONF_TEMPERATURE_ENTITY_ID,
            CONF_HUMIDITY_ENTITY_ID,
            CONF_CO2_ENTITY_ID,
        ):
            if values.get(field_key):
                continue
            errors[_zone_field_key(zone_index, field_key)] = (
                "writeback_entities_required"
            )
    return errors


def validate_button_configuration(
    feature_enabled: bool,
    detected_button_zone_indexes: set[int],
    button_modes: Mapping[tuple[int, int], str],
    button_timers: Mapping[tuple[int, int], int],
) -> dict[str, str]:
    """Validate button enablement and per-button settings."""
    errors: dict[str, str] = {}
    if not feature_enabled:
        return errors

    if not detected_button_zone_indexes:
        errors["base"] = "external_buttons_require_detected_zone"
        return errors

    for button_key, button_mode in button_modes.items():
        zone_index, button_index = button_key
        if button_mode not in {BUTTON_MODE_BOOST, BUTTON_MODE_DIGESTOR}:
            errors[_button_field_key(zone_index, button_index, CONF_BUTTON_MODE)] = (
                "invalid_button_mode"
            )
        if button_timers.get(button_key, 0) < 1:
            errors[
                _button_field_key(zone_index, button_index, CONF_MAX_ACTIVE_SECONDS)
            ] = "button_active_seconds_too_low"
        if button_timers.get(button_key, 0) > MAX_BUTTON_ACTIVE_SECONDS:
            errors[
                _button_field_key(zone_index, button_index, CONF_MAX_ACTIVE_SECONDS)
            ] = "button_active_seconds_too_high"
    return errors


def _zone_field_key(zone_index: int, field_key: str) -> str:
    return f"zone_{zone_index}_{field_key}"


def _button_field_key(zone_index: int, button_index: int, field_key: str) -> str:
    return f"zone_{zone_index}_button_{button_index}_{field_key}"


def _group_indexed_bits(
    bitmap: int, group_size: int, max_groups: int
) -> dict[int, tuple[int, ...]]:
    grouped: dict[int, list[int]] = {}
    for bit_index in range(group_size * max_groups):
        if not bitmap & (1 << bit_index):
            continue
        zone_index = (bit_index // group_size) + 1
        within_zone_index = (bit_index % group_size) + 1
        grouped.setdefault(zone_index, []).append(within_zone_index)
    return {zone_index: tuple(indexes) for zone_index, indexes in grouped.items()}


# Canonical v3 validation is shared by UI, migration, and runtime.
METRIC_TARGET_UNITS = {
    "temperature": "°C",
    "floor_temperature": "°C",
    "humidity": "%",
    "co2": "ppm",
}


def metric_unit_is_valid(metric: str, unit: Any, assumption: str | None = None) -> bool:
    """Validate units, including an explicitly confirmed unitless assumption."""
    target = METRIC_TARGET_UNITS.get(metric)
    if target is None:
        return False
    if unit in (None, ""):
        return assumption == target
    if target == "°C":
        return unit in ("°C", "C", "degC", "°F", "degF")
    return unit == target


def normalize_metric_value(
    metric: str, value: Any, unit: Any, assumption: str | None = None
) -> float | None:
    """Return a finite in-range target-unit value, never clamp or round."""
    import math

    if isinstance(value, bool) or not metric_unit_is_valid(metric, unit, assumption):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(result):
        return None
    if metric in ("temperature", "floor_temperature") and unit in ("°F", "degF"):
        result = (result - 32) * 5 / 9
    low, high = {
        "temperature": (-20, 100),
        "floor_temperature": (-20, 100),
        "humidity": (0, 100),
        "co2": (0, 10000),
    }[metric]
    return result if low <= result <= high else None


def validate_runtime_options(values: Mapping[str, Any]) -> dict[str, str]:
    """Strict types prevent string booleans and fractional cadence from saving."""
    errors: dict[str, str] = {}
    limits = {
        "read_interval_ms": (1000, 86400000),
        "write_interval_ms": (5000, 86400000),
        "scan_interval_s": (5, 86400),
        "stale_after_s": (1, 86400),
        "force_resync_every_s": (1, 86400),
    }
    for key, (low, high) in limits.items():
        value = values.get(key)
        if type(value) is not int or not low <= value <= high:
            errors[key] = "invalid_interval"
    for key in ("bridge_enabled", "write_on_change_only"):
        if type(values.get(key)) is not bool:
            errors[key] = "invalid_boolean"
    if values.get("log_level_bridge") not in ("normal", "debug"):
        errors["log_level_bridge"] = "invalid_log_level"
    if (
        not errors
        and values["force_resync_every_s"] < (values["write_interval_ms"] + 999) // 1000
    ):
        errors["force_resync_every_s"] = "watchdog_too_short"
    return errors
