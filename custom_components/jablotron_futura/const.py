"""Constants for the Jablotron Futura integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "jablotron_futura"

CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_UNIT_ID: Final = "unit_id"
CONF_PROFILE_MODE: Final = "profile_mode"
CONF_RESOLVED_PROFILE: Final = "resolved_profile"
CONF_SCAN_INTERVAL_S: Final = "scan_interval_s"

CONF_BRIDGE_ENABLED: Final = "bridge_enabled"
CONF_BRIDGE_UPDATE_INTERVAL_S: Final = "bridge_update_interval_s"
CONF_STALE_AFTER_S: Final = "stale_after_s"
CONF_WRITE_ON_CHANGE_ONLY: Final = "write_on_change_only"
CONF_FORCE_RESYNC_EVERY_S: Final = "force_resync_every_s"
CONF_LOG_LEVEL_BRIDGE: Final = "log_level_bridge"
CONF_SHOW_COMMISSIONING_NOTICE: Final = "show_commissioning_notice"
CONF_EXTERNAL_SENSOR_SLOTS: Final = "external_sensor_slots"

CONF_ENABLED: Final = "enabled"
CONF_SLOT_NAME: Final = "slot_name"
CONF_TEMPERATURE_ENTITY_ID: Final = "temperature_entity_id"
CONF_HUMIDITY_ENTITY_ID: Final = "humidity_entity_id"
CONF_CO2_ENTITY_ID: Final = "co2_entity_id"
CONF_FLOOR_TEMPERATURE_ENTITY_ID: Final = "floor_temperature_entity_id"

PROFILE_MODE_AUTO: Final = "auto"
PROFILE_FUTURA_LMS: Final = "futura_lms"
PROFILE_FUTURA_LP: Final = "futura_lp"

LOG_LEVEL_NORMAL: Final = "normal"
LOG_LEVEL_DEBUG: Final = "debug"

SUPPORTED_PROFILE_MODES: Final = (
    PROFILE_MODE_AUTO,
    PROFILE_FUTURA_LMS,
    PROFILE_FUTURA_LP,
)
SUPPORTED_PROFILES: Final = (
    PROFILE_FUTURA_LMS,
    PROFILE_FUTURA_LP,
)

DEFAULT_PORT: Final = 502
DEFAULT_UNIT_ID: Final = 1
DEFAULT_SCAN_INTERVAL_S: Final = 5

DEFAULT_BRIDGE_ENABLED: Final = True
DEFAULT_BRIDGE_UPDATE_INTERVAL_S: Final = 10
DEFAULT_STALE_AFTER_S: Final = 120
DEFAULT_WRITE_ON_CHANGE_ONLY: Final = True
DEFAULT_FORCE_RESYNC_EVERY_S: Final = 300
DEFAULT_LOG_LEVEL_BRIDGE: Final = LOG_LEVEL_NORMAL
DEFAULT_SHOW_COMMISSIONING_NOTICE: Final = True

SLOT_COUNT: Final = 8
ALLOWED_SOURCE_DOMAINS: Final = ("sensor", "number", "input_number")

PLATFORMS: Final = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.BUTTON,
]

METRIC_TEMPERATURE: Final = "temperature"
METRIC_HUMIDITY: Final = "humidity"
METRIC_CO2: Final = "co2"
METRIC_FLOOR_TEMPERATURE: Final = "floor_temperature"

METRIC_TO_ENTITY_KEY: Final = {
    METRIC_TEMPERATURE: CONF_TEMPERATURE_ENTITY_ID,
    METRIC_HUMIDITY: CONF_HUMIDITY_ENTITY_ID,
    METRIC_CO2: CONF_CO2_ENTITY_ID,
    METRIC_FLOOR_TEMPERATURE: CONF_FLOOR_TEMPERATURE_ENTITY_ID,
}

METRIC_TO_INVALID_BIT: Final = {
    METRIC_TEMPERATURE: 0,
    METRIC_HUMIDITY: 1,
    METRIC_CO2: 2,
    METRIC_FLOOR_TEMPERATURE: 3,
}

COMMISSIONING_NOTICE: Final = (
    "Futura must already be commissioned outside Home Assistant. "
    "This integration does not replace MyCOMPANY commissioning, "
    "analog input configuration, or emergency shutdown wiring."
)

EMERGENCY_WARNING_BIT: Final = 11
ENTRY_TITLE_PREFIX: Final = "Jablotron Futura"
