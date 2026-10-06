"""Constants for the Jablotron Futura integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "jablotron_futura"

CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_UNIT_ID: Final = "unit_id"
CONF_VARIOBREEZE: Final = "variobreeze"
CONF_PROFILE_MODE: Final = "profile_mode"
CONF_RESOLVED_PROFILE: Final = "resolved_profile"
CONF_SCAN_INTERVAL_S: Final = "scan_interval_s"
CONF_DEVICE_IDENTITY: Final = "device_identity"
CONF_DEVICE_VARIANT: Final = "device_variant"
CONF_SERIAL_NUMBER: Final = "serial_number"
CONF_ETHERNET_MAC: Final = "ethernet_mac"
CONF_HARDWARE_REVISION: Final = "hardware_revision"
CONF_FIRMWARE_REVISION: Final = "firmware_revision"

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
CONF_ZONE_CONFIGS: Final = "zone_configs"
CONF_ZONE_ENABLED: Final = "zone_enabled"
CONF_ZONE_INDEX: Final = "zone_index"
CONF_ZONE_NAME: Final = "zone_name"
CONF_ZONE_TYPE: Final = "zone_type"
CONF_AREA_ID: Final = "area_id"
CONF_DAMPER_NAMES: Final = "damper_names"
CONF_SUPPLY_DAMPER_IDS: Final = "supply_damper_ids"
CONF_EXHAUST_DAMPER_IDS: Final = "exhaust_damper_ids"
CONF_ALFA_INDEX: Final = "alfa_index"
CONF_EXTERNAL_SENSOR_MODE: Final = "external_sensor_mode"
CONF_SENSOR_MODE: Final = "sensor_mode"
CONF_WRITEBACK_ENABLED: Final = "writeback_enabled"
CONF_WRITE_INTERVAL_MS: Final = "write_interval_ms"
CONF_READ_INTERVAL_MS: Final = "read_interval_ms"
CONF_EXTERNAL_BUTTONS_ENABLED: Final = "external_buttons_enabled"
CONF_BUTTON_CONFIGS: Final = "button_configs"
CONF_BUTTON_IDS: Final = "button_ids"
CONF_BUTTON_INDEX: Final = "button_index"
CONF_BUTTON_MODE: Final = "button_mode"
CONF_EXT_BUTTON_MODE: Final = "ext_button_mode"
CONF_DEFAULT_TIMER_SECONDS: Final = "default_timer_seconds"
CONF_MAX_ACTIVE_SECONDS: Final = "max_active_seconds"

PROFILE_MODE_AUTO: Final = "auto"
PROFILE_FUTURA_LMS: Final = "futura_lms"
PROFILE_FUTURA_LP: Final = "futura_lp"

LOG_LEVEL_NORMAL: Final = "normal"
LOG_LEVEL_DEBUG: Final = "debug"

SUPPORTED_PROFILE_MODES: Final = (
    PROFILE_MODE_AUTO,
    PROFILE_FUTURA_LMS,
)
SUPPORTED_PROFILES: Final = (PROFILE_FUTURA_LMS,)

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
ZONE_COUNT: Final = 8
MAX_DAMPERS_PER_ZONE: Final = 4
MAX_BUTTONS_PER_ZONE: Final = 2
ALLOWED_SOURCE_DOMAINS: Final = ("sensor", "number", "input_number")

EXTERNAL_SENSOR_MODE_OBSERVE_ONLY: Final = "observe_only"
EXTERNAL_SENSOR_MODE_HA_WRITEBACK: Final = "ha_writeback"

# v2 per-zone sensor modes
SENSOR_MODE_NONE: Final = "none"
SENSOR_MODE_READ: Final = "read"
SENSOR_MODE_HA_WRITEBACK: Final = "ha_writeback"

# v2 per-zone external button modes
EXT_BUTTON_MODE_NONE: Final = "none"
EXT_BUTTON_MODE_FUTURA: Final = "futura"
EXT_BUTTON_MODE_HA_CONTROL: Final = "ha_control"

BUTTON_MODE_BOOST: Final = "boost"
BUTTON_MODE_DIGESTOR: Final = "digestor"

DEFAULT_EXTERNAL_SENSOR_MODE: Final = EXTERNAL_SENSOR_MODE_OBSERVE_ONLY
DEFAULT_WRITE_INTERVAL_MS: Final = 12000
DEFAULT_READ_INTERVAL_MS: Final = 10000
MIN_WRITE_INTERVAL_MS: Final = 5000
MIN_READ_INTERVAL_MS: Final = 1000
DEFAULT_EXTERNAL_BUTTONS_ENABLED: Final = False
DEFAULT_BUTTON_MAX_ACTIVE_SECONDS: Final = 180
DEFAULT_DIGESTOR_TIMER_SECONDS: Final = 300
MAX_BUTTON_ACTIVE_SECONDS: Final = 10800

# VarioBreeze bit in fut_config register
VARIOBREEZE_BIT: Final = 4

# Config entry version
CONFIG_VERSION: Final = 3

CONF_ZONES: Final = "zones"
CONF_SENSOR_SLOTS: Final = "sensor_slots"
CONF_BUTTON_SLOTS: Final = "button_slots"
CONF_RUNTIME: Final = "runtime"
CONF_IDENTITY_TOKEN: Final = "identity_token"
CONF_MIGRATION_NEEDS_REPAIR: Final = "migration_needs_repair"

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

FUTURA_DEVICE_ID: Final = 39
EMERGENCY_WARNING_BIT: Final = 11
ENTRY_TITLE_PREFIX: Final = "Jablotron Futura"
