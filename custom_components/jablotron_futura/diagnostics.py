"""Privacy-preserving runtime diagnostics, including nested migration evidence."""

from __future__ import annotations


import hashlib
import re

from typing import Any


from homeassistant.core import HomeAssistant

from .models import FuturaConfigEntry


REDACTED = "**REDACTED**"

SENSITIVE = {
    "host",
    "port",
    "serial_number",
    "ethernet_mac",
    "title",
    "unique_id",
    "identity_token",
    "entry_id",
    "device_id",
    "device_ids",
    "name",
    "slot_name",
    "zone_name",
    "area_id",
    "area",
    "damper_names",
    "entity_identity_suffix",
}

SAFE_TEXT = {
    "visibility_load_failed",
    "visibility_save_failed",
    "visibility_identity_changed",
    "visibility_transition_incomplete",
    "visibility_registry_failed",
    "visibility_registry_save_failed",
    "none",
    "read",
    "ha_writeback",
    "futura",
    "ha_control",
    "boost",
    "digestor",
    "normal",
    "debug",
    "futura_lms",
    "auto",
    "°C",
    "°F",
    "C",
    "degC",
    "degF",
    "%",
    "ppm",
    "s",
    "ok",
    "failed",
    "skipped_timeout",
    "missing",
    "unknown",
    "unavailable",
    "stale",
    "invalid",
    "invalid_timestamp",
    "ready",
    "active",
    "sending",
    "startup",
    "clear_pending",
    "cleanup_failed",
    "read_failed",
    "write_failed",
    "clear_failed",
    "deadline",
    "sensor",
    "button",
    "transport_failure",
    "modbus_error",
    "identity_mismatch",
    "timer",
    "reconnect",
    "source_changed",
    "watchdog",
    "low_word_first",
    "registration_failed",
    "ha_activation_deadline",
    "futura_raw_register",
}

# Only schema-owned keys are readable. Migration archives and future payloads
# can contain arbitrary private names as keys, not merely as values.
SAFE_KEYS = SENSITIVE | set(
    """
config_entry data options version minor_version domain source runtime
sensor_visibility button_visibility configured_count suppressed_count user_override_count listening
device_identity device_variant hardware_revision firmware_revision
variobreeze coordinator_data bridge external_buttons sensor_readback button_readback
scheduler clear_report button_recovery transport migration_archive original_data
original_options conflicts field error error_code value status source_snapshot
temperature humidity co2 floor_temperature temperature_entity_id humidity_entity_id
co2_entity_id floor_temperature_entity_id unit unitless_assumptions
sensor_slots button_slots zones enabled mode ownership zone_binding button_mode
default_timer_seconds max_active_seconds bridge_enabled read_interval_ms
write_interval_ms scan_interval_s stale_after_s write_on_change_only
force_resync_every_s log_level_bridge migration_needs_repair
resolved_profile profile_label profile_mode unit_id slot slot_index kind old_profile
generation activation_generation result attempted_at cleanup_result state deadline
present invalidate_mask unknown_invalid_bits raw last_raw timestamp last_timestamp
read_monotonic available remaining_seconds active mismatch decoded bits
last_attempt_at last_successful_write_at last_error last_reason last_payload
pending_write_reason temperature_raw humidity_raw co2_raw floor_temperature_raw
slots slot_states owned recovery states last_reported last_updated
requested_interval_ms effective_interval_s last_started_monotonic coalesced
duration_s delayed lock_wait_s topology_snapshot connected_supply_valves_bits
connected_exhaust_valves_bits connected_buttons_bits connected_alfa_bits
alfa_connected_bits alfa_count vzv_identify_bits supply_damper_ids
exhaust_damper_ids button_ids alfa_index zone_index supply_identify exhaust_identify
external_sensor_present external_button_present alfa_live_values external_sensor_live_values
mb_address ntc_temperature fact_device_id variant_raw fut_config_raw modes_bits_raw
errors_bits_raw warnings_bits_raw emergency_shutdown_active last_poll_at
status_words status_word_order status_flags valid active_bits known_active_bits
unknown_bits unknown_bits_mask
registered registration_pending registration_generation countdown_source
has_internal_heater has_coolbreeze_cooling has_coolbreeze_heating has_bypass
heating_available cooling_available bypass_available filter_wear power heat_recovering
heating_power air_flow fan_power_supply_raw fan_power_exhaust_raw fan_rpm_supply
fan_rpm_exhaust rtc_batt_voltage temp_outdoor_ntc mode_raw mode_text temp_set_raw
humi_set_raw time_program_raw antiradon_raw bypass_enable_raw heating_enable_raw
cooling_enable_raw comfort_enable_raw away_begin_ts away_end_ts away_begin_text
away_end_text
""".split()
)
SAFE_KEYS.update(str(slot) for slot in range(1, 9))
SAFE_KEYS.update(
    f"{kind}_{slot}" for kind in ("supply", "exhaust") for slot in range(1, 9)
)
SAFE_KEYS.update(
    f"alfa_{field}_{slot}"
    for field in (
        "available",
        "mb_address",
        "options",
        "co2",
        "temp",
        "humi",
        "ntc_temp",
    )
    for slot in range(1, 9)
)
SAFE_KEYS.update(
    f"{metric}_{side}"
    for metric in ("temp", "humi")
    for side in ("outdoor", "supply", "extract", "exhaust")
)
SAFE_KEYS.update(
    f"{mode}_remaining_{unit}"
    for mode in ("boost", "circulation", "overpressure", "night", "party")
    for unit in ("s", "min", "h")
)


def redact(value: Any, key: str = "") -> Any:
    """Allow numeric diagnostics and known status vocabulary; redact arbitrary text."""

    if key in SENSITIVE or key.endswith("_entity_id") or key.endswith("_name"):
        if key.endswith("_entity_id") and isinstance(value, str):
            return "source_" + hashlib.sha256(value.encode()).hexdigest()[:10]

        return REDACTED

    if isinstance(value, dict):
        return {
            (
                str(k)
                if str(k) in SAFE_KEYS
                else "field_" + hashlib.sha256(str(k).encode()).hexdigest()[:10]
            ): redact(v, str(k))
            for k, v in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [redact(item, key) for item in value]

    if isinstance(value, str):
        return (
            value
            if value in SAFE_TEXT
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}T[0-9:.]+(?:\+00:00|Z)", value)
            else REDACTED
        )

    if value is None or isinstance(value, (bool, int, float)):
        return value

    return REDACTED


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FuturaConfigEntry
) -> dict[str, Any]:

    runtime = entry.runtime_data

    coordinator = runtime.coordinator

    return redact(
        {
            "config_entry": entry.as_dict(),
            "coordinator_data": coordinator.data,
            "bridge": runtime.bridge.diagnostics_snapshot(),
            "external_buttons": coordinator.external_button_diagnostics_snapshot(),
            "sensor_readback": coordinator.sensor_readback,
            "button_readback": coordinator.button_readback,
            "scheduler": coordinator.scheduler,
            "clear_report": coordinator.clear_report,
            "button_recovery": coordinator.button_recovery,
            "sensor_visibility": runtime.sensor_visibility.snapshot()
            if getattr(runtime, "sensor_visibility", None) is not None
            else None,
            "button_visibility": runtime.button_visibility.snapshot()
            if getattr(runtime, "button_visibility", None) is not None
            else None,
            "transport": {
                "generation": coordinator.reconnect_generation,
                "lock_wait_s": coordinator._transport.last_lock_wait
                if coordinator._transport
                else None,
            },
        }
    )
