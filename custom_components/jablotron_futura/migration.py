"""Lossless legacy-to-canonical migration; this module never opens transport."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from .identity import identity_token, normalize_host
from .models import default_v3_options, load_v3_options, validate_v3_options
from .validation import METRIC_TARGET_UNITS, validate_runtime_options


def migrate_configuration(
    data: dict[str, Any],
    options: dict[str, Any],
    version: int,
    unique_id: str | None,
    entry_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Archive the complete original before interpreting any legacy projection."""
    if version == 3:
        return deepcopy(data), load_v3_options(options)
    if (
        version not in (1, 2)
        or not isinstance(data, dict)
        or not isinstance(options, dict)
    ):
        raise ValueError("migration_failed")
    # Storage must be able to represent the original without lossy repr conversion.
    json.dumps([data, options], allow_nan=False)
    original = deepcopy(options)
    result = default_v3_options()
    conflicts: list[dict[str, Any]] = []
    archive = {
        "original_data": deepcopy(data),
        "original_options": original,
        "conflicts": conflicts,
    }
    result["migration_archive"] = archive

    def conflict(field: str, value: Any, error: str = "migration_conflict") -> None:
        conflicts.append({"field": field, "error": error, "value": deepcopy(value)})

    raw_runtime = {**data, **options}
    for key in result["runtime"]:
        if key in raw_runtime:
            result["runtime"][key] = raw_runtime[key]
    if (
        "write_interval_ms" not in raw_runtime
        and "bridge_update_interval_s" in raw_runtime
        and "zone_configs" not in options
        and "v2_zones" not in options
    ):
        interval = raw_runtime["bridge_update_interval_s"]
        result["runtime"]["write_interval_ms"] = (
            interval * 1000 if type(interval) is int else interval
        )
    runtime_errors = validate_runtime_options(result["runtime"])
    if runtime_errors:
        archive["runtime_inputs"] = {
            key: deepcopy(value)
            for key, value in raw_runtime.items()
            if key in result["runtime"] or key == "bridge_update_interval_s"
        }
        for key, error in runtime_errors.items():
            conflict(f"runtime.{key}", result["runtime"].get(key), error)
        result["runtime"] = default_v3_options()["runtime"]
    result["variobreeze"] = options.get(
        "variobreeze", bool(options.get("zone_configs"))
    )
    if type(result["variobreeze"]) is not bool:
        conflict("variobreeze", result["variobreeze"], "invalid_boolean")
        result["variobreeze"] = False
    legacy_zones = options.get("zone_configs", [])
    flat = options.get("external_sensor_slots", [])
    v2 = options.get("v2_zones", {})
    if (
        not isinstance(legacy_zones, list)
        or not isinstance(flat, list)
        or not isinstance(v2, dict)
    ):
        raise ValueError("migration_failed")
    if any(not isinstance(row, dict) for row in [*legacy_zones, *flat, *v2.values()]):
        raise ValueError("migration_failed")

    def meta(target: str, raw: dict[str, Any]) -> None:
        row = result["zones"][target]
        row.update(
            {
                "enabled": raw.get("zone_enabled", raw.get("enabled", False)),
                "name": raw.get("zone_name", raw.get("name", "")),
                "area_id": raw.get("area_id"),
            }
        )
        for key in (
            "supply_damper_ids",
            "exhaust_damper_ids",
            "damper_names",
            "alfa_index",
            "button_ids",
        ):
            if key in raw:
                row[key] = deepcopy(raw[key])

    for i, raw in enumerate(legacy_zones, 1):
        if i > 8:
            conflict("zones", raw, "invalid_slot")
            continue
        for side in ("supply", "exhaust"):
            meta(f"{side}_{i}", raw)
    for key, raw in v2.items():
        if key not in result["zones"]:
            conflict(f"zones.{key}", raw, "invalid_slot")
        else:
            meta(key, raw)

    # Presence of v2, including {}, shadows lower-priority active sensor choices.
    if "v2_zones" in options:
        sensors = [
            (int(key.split("_")[1]), raw, "v2")
            for key, raw in v2.items()
            if key in result["zones"] and key.startswith("supply_")
        ]
    elif "zone_configs" in options:
        sensors = [(i, raw, "zone") for i, raw in enumerate(legacy_zones, 1)]
    else:
        sensors = [
            (raw.get("slot_index", i), raw, "flat") for i, raw in enumerate(flat, 1)
        ]
    occupied: set[int] = set()
    for index, raw, kind in sensors:
        if type(index) is not int or not 1 <= index <= 8:
            conflict("sensor_slots", raw, "invalid_slot")
            continue
        row = result["sensor_slots"][str(index)]
        if index in occupied:
            conflict(f"sensor_slots.{index}", raw)
            row["enabled"] = False
            continue
        occupied.add(index)
        row["enabled"] = raw.get("enabled" if kind == "flat" else "zone_enabled", False)
        row["name"] = raw.get("slot_name" if kind == "flat" else "zone_name", "")
        row["zone_binding"] = None if kind == "flat" else f"supply_{index}"
        if kind == "v2":
            row["mode"] = raw.get("sensor_mode", "none")
        elif kind == "flat":
            row["mode"] = "ha_writeback"
        else:
            mode = options.get("external_sensor_mode", "observe_only")
            row["mode"] = (
                "read"
                if mode == "observe_only"
                else "ha_writeback"
                if mode == "ha_writeback" and raw.get("writeback_enabled", False)
                else "none"
            )
            if mode not in ("observe_only", "ha_writeback"):
                conflict(f"sensor_slots.{index}.mode", mode, "invalid_sensor_mode")
        for metric, unit in METRIC_TARGET_UNITS.items():
            field = f"{metric}_entity_id"
            row[field] = raw.get(field) or None
            if metric == "floor_temperature" and kind != "flat":
                candidates = [
                    entry.get(field)
                    for entry in (
                        [legacy_zones[index - 1]] if index <= len(legacy_zones) else []
                    )
                    + [
                        entry
                        for j, entry in enumerate(flat, 1)
                        if entry.get("slot_index", j) == index
                    ]
                    if entry.get(field)
                ]
                values = set(candidates + ([row[field]] if row[field] else []))
                if len(values) > 1:
                    conflict(
                        f"sensor_slots.{index}.{field}",
                        list(values),
                        "conflicting_floor",
                    )
                    row["enabled"] = False
                elif values:
                    row[field] = next(iter(values))
            if row[field]:
                row["unitless_assumptions"][metric] = unit
                archive.setdefault("warnings", []).append(
                    {"slot": index, "metric": metric, "code": "migrated_assumption"}
                )

    occupied_buttons: dict[int, dict[str, Any]] = {}
    legacy_button_zones: set[int] = set()

    def button(
        index: Any,
        raw: dict[str, Any],
        zone: int,
        ordinal: int,
        projection: bool = False,
    ) -> None:
        if type(index) is not int or not 1 <= index <= 8:
            conflict("button_slots", raw, "ambiguous_button_slot")
            return
        candidate = deepcopy(result["button_slots"][str(index)])
        candidate.update(
            {
                "enabled": raw.get("enabled", raw.get("zone_enabled", False)),
                "ownership": raw.get(
                    "ext_button_mode",
                    "ha_control"
                    if options.get("external_buttons_enabled", False)
                    else "none",
                ),
                "name": raw.get("name", raw.get("zone_name", "")),
                "zone_binding": f"exhaust_{zone}",
                "button_mode": raw.get("button_mode", "boost"),
                "default_timer_seconds": raw.get(
                    "default_timer_seconds", raw.get("max_active_seconds", 180)
                ),
                "max_active_seconds": raw.get("max_active_seconds", 10800),
                "entity_identity_suffix": raw.get(
                    "entity_identity_suffix", f"zone_{zone}_button_{ordinal}"
                ),
            }
        )
        if index in occupied_buttons:
            previous = occupied_buttons[index]
            comparable = ("ownership", "button_mode", "default_timer_seconds")
            if projection and all(
                previous[key] == candidate[key] for key in comparable
            ):
                return
            conflict(f"button_slots.{index}", [previous, candidate], "button_collision")
            result["button_slots"][str(index)]["enabled"] = False
            return
        occupied_buttons[index] = candidate
        result["button_slots"][str(index)] = candidate

    for zone, raw in enumerate(legacy_zones, 1):
        buttons = raw.get("button_configs", [])
        if not isinstance(buttons, list):
            raise ValueError("migration_failed")
        if not buttons:
            continue
        legacy_button_zones.add(zone)
        ids = raw.get("button_ids", [])
        for ordinal, saved in enumerate(buttons, 1):
            if not isinstance(saved, dict):
                raise ValueError("migration_failed")
            slot = saved.get("slot_index", saved.get("button_id"))
            if (
                slot is None
                and isinstance(ids, list)
                and len(ids) == len(buttons)
                and all(type(item) is int for item in ids)
                and len(set(ids)) == len(ids)
            ):
                slot = ids[ordinal - 1]
            button(
                slot,
                {
                    **saved,
                    "name": raw.get("zone_name", ""),
                    "enabled": saved.get("enabled", False)
                    and raw.get("zone_enabled", False),
                },
                zone,
                saved.get("button_index", ordinal),
            )
    for key, raw in v2.items():
        if key not in result["zones"] or not key.startswith("exhaust_"):
            continue
        zone = int(key.split("_")[1])
        slot = raw.get("slot_index", raw.get("button_id", zone))
        if zone in legacy_button_zones:
            ids = legacy_zones[zone - 1].get("button_ids", [])
            if ids:
                slot = ids[0]
        button(slot, raw, zone, 1, projection=zone in legacy_button_zones)

    # Invalid local fields retain originals in archive and disable their slots.
    errors = validate_v3_options(result)
    defaults = default_v3_options()
    for field, error in errors.items():
        parts = field.split(".")
        conflict(field, deepcopy(result.get(parts[0])), error)
        if len(parts) >= 3 and parts[0] in ("sensor_slots", "button_slots", "zones"):
            group, index, key = parts[:3]
            result[group][index][key] = deepcopy(defaults[group][index].get(key))
            result[group][index]["enabled"] = False
            if group == "button_slots" and key == "default_timer_seconds":
                maximum = result[group][index]["max_active_seconds"]
                if type(maximum) is int and 1 <= maximum <= 10800:
                    result[group][index][key] = min(180, maximum)
            if group == "button_slots" and key == "entity_identity_suffix":
                used = {
                    row["entity_identity_suffix"]
                    for row in result[group].values()
                    if isinstance(row["entity_identity_suffix"], str)
                }
                suffix = f"migration_repair_button_{index}"
                while suffix in used:
                    suffix += "_repair"
                result[group][index][key] = suffix
        else:
            raise ValueError("migration_failed", errors)
    result["migration_needs_repair"] = bool(conflicts)
    result = load_v3_options(result)
    new_data = deepcopy(data)
    new_data.pop("scan_interval_s", None)
    if "host" in new_data:
        new_data["host"] = normalize_host(str(new_data["host"]))
    new_data.setdefault("identity_token", identity_token(unique_id, entry_id))
    return new_data, result
