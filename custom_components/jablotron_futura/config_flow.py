"""Config flow for Jablotron Futura."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er, selector

from .const import (
    ALLOWED_SOURCE_DOMAINS,
    COMMISSIONING_NOTICE,
    CONF_BRIDGE_ENABLED,
    CONF_BRIDGE_UPDATE_INTERVAL_S,
    CONF_CO2_ENTITY_ID,
    CONF_ENABLED,
    CONF_EXTERNAL_SENSOR_SLOTS,
    CONF_FLOOR_TEMPERATURE_ENTITY_ID,
    CONF_FORCE_RESYNC_EVERY_S,
    CONF_HOST,
    CONF_HUMIDITY_ENTITY_ID,
    CONF_LOG_LEVEL_BRIDGE,
    CONF_PORT,
    CONF_PROFILE_MODE,
    CONF_SCAN_INTERVAL_S,
    CONF_SHOW_COMMISSIONING_NOTICE,
    CONF_SLOT_NAME,
    CONF_STALE_AFTER_S,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_UNIT_ID,
    CONF_WRITE_ON_CHANGE_ONLY,
    DEFAULT_LOG_LEVEL_BRIDGE,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL_S,
    DEFAULT_UNIT_ID,
    DOMAIN,
    LOG_LEVEL_DEBUG,
    LOG_LEVEL_NORMAL,
    PROFILE_FUTURA_LMS,
    PROFILE_FUTURA_LP,
    PROFILE_MODE_AUTO,
    SLOT_COUNT,
)
from .coordinator import (
    CannotConnectError,
    InvalidProfileError,
    NotFuturaDeviceError,
    async_validate_connection,
    make_entry_data,
)
from .models import (
    BridgeOptions,
    ExternalSensorSlotConfig,
    default_options,
    dump_slot_configs,
    load_slot_configs,
)
from .validation import has_duplicate_unique_id, validate_global_options


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Jablotron Futura."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial user flow."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                validation = await _async_validate_user_connection(user_input)
            except CannotConnectError:
                errors["base"] = "cannot_connect"
            except InvalidProfileError:
                errors["base"] = "invalid_profile"
            except NotFuturaDeviceError:
                errors["base"] = "not_futura_device"
            else:
                await self.async_set_unique_id(validation.unique_id, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=validation.title,
                    data=make_entry_data(user_input, validation),
                    options=default_options(),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_connection_schema(user_input),
            errors=errors,
            description_placeholders={"commissioning_notice": COMMISSIONING_NOTICE},
        )

    async def async_step_reconfigure(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        """Handle entry reconfiguration."""
        entry = self._get_reconfigure_entry()
        current = dict(entry.data)
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                validation = await _async_validate_user_connection(dict(user_input))
            except CannotConnectError:
                errors["base"] = "cannot_connect"
            except InvalidProfileError:
                errors["base"] = "invalid_profile"
            except NotFuturaDeviceError:
                errors["base"] = "not_futura_device"
            else:
                if has_duplicate_unique_id(
                    self._async_current_entries(),
                    entry.entry_id,
                    validation.unique_id,
                ):
                    errors["base"] = "already_configured"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        unique_id=validation.unique_id,
                        title=validation.title,
                        data=make_entry_data(dict(user_input), validation),
                    )

        defaults = {
            CONF_HOST: current[CONF_HOST],
            CONF_PORT: current.get(CONF_PORT, DEFAULT_PORT),
            CONF_UNIT_ID: current.get(CONF_UNIT_ID, DEFAULT_UNIT_ID),
            CONF_PROFILE_MODE: current.get(CONF_PROFILE_MODE, PROFILE_MODE_AUTO),
            CONF_SCAN_INTERVAL_S: current.get(
                CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S
            ),
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_connection_schema(defaults),
            errors=errors,
            description_placeholders={"commissioning_notice": COMMISSIONING_NOTICE},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "JablotronFuturaOptionsFlow":
        """Create the options flow."""
        return JablotronFuturaOptionsFlow(config_entry)


class JablotronFuturaOptionsFlow(config_entries.OptionsFlow):
    """Multi-step options flow for bridge settings and slot mapping."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry
        merged_options = default_options()
        merged_options.update(
            {
                key: value
                for key, value in entry.options.items()
                if key != CONF_EXTERNAL_SENSOR_SLOTS
            }
        )
        if CONF_EXTERNAL_SENSOR_SLOTS in entry.options:
            merged_options[CONF_EXTERNAL_SENSOR_SLOTS] = entry.options[
                CONF_EXTERNAL_SENSOR_SLOTS
            ]

        self.bridge_options = BridgeOptions.from_mapping(merged_options)
        self.slot_configs = load_slot_configs(merged_options)

    async def async_step_init(self, _user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_global()

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_global_options(user_input)
            if not errors:
                self.bridge_options = BridgeOptions.from_mapping(user_input)
                return await self.async_step_slot_1()

        defaults = self.bridge_options.as_dict()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_BRIDGE_ENABLED,
                    default=defaults[CONF_BRIDGE_ENABLED],
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_BRIDGE_UPDATE_INTERVAL_S,
                    default=defaults[CONF_BRIDGE_UPDATE_INTERVAL_S],
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=5,
                        step=1,
                    )
                ),
                vol.Required(
                    CONF_STALE_AFTER_S,
                    default=defaults[CONF_STALE_AFTER_S],
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=10,
                        step=1,
                    )
                ),
                vol.Required(
                    CONF_WRITE_ON_CHANGE_ONLY,
                    default=defaults[CONF_WRITE_ON_CHANGE_ONLY],
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_FORCE_RESYNC_EVERY_S,
                    default=defaults[CONF_FORCE_RESYNC_EVERY_S],
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=60,
                        step=1,
                    )
                ),
                vol.Required(
                    CONF_LOG_LEVEL_BRIDGE,
                    default=defaults[CONF_LOG_LEVEL_BRIDGE],
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[LOG_LEVEL_NORMAL, LOG_LEVEL_DEBUG],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_SHOW_COMMISSIONING_NOTICE,
                    default=defaults[CONF_SHOW_COMMISSIONING_NOTICE],
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="global",
            data_schema=schema,
            errors=errors,
            description_placeholders={"commissioning_notice": COMMISSIONING_NOTICE},
        )

    async def async_step_slot_1(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._async_slot_step(1, user_input)

    async def async_step_slot_2(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._async_slot_step(2, user_input)

    async def async_step_slot_3(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._async_slot_step(3, user_input)

    async def async_step_slot_4(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._async_slot_step(4, user_input)

    async def async_step_slot_5(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._async_slot_step(5, user_input)

    async def async_step_slot_6(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._async_slot_step(6, user_input)

    async def async_step_slot_7(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._async_slot_step(7, user_input)

    async def async_step_slot_8(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._async_slot_step(8, user_input)

    async def async_step_summary(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=self._serialize_options())

        configured_slots = ", ".join(
            str(slot_config.slot_index)
            for slot_config in self.slot_configs
            if slot_config.enabled
        )
        return self.async_show_form(
            step_id="summary",
            data_schema=vol.Schema({}),
            description_placeholders={
                "configured_slots": configured_slots or "-",
            },
        )

    async def _async_slot_step(
        self, slot_index: int, user_input: dict[str, Any] | None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _async_validate_slot(self.hass, user_input)
            if not errors:
                self.slot_configs[slot_index - 1] = ExternalSensorSlotConfig.from_mapping(
                    slot_index, user_input
                )
                next_step = (
                    "summary" if slot_index == SLOT_COUNT else f"slot_{slot_index + 1}"
                )
                return await getattr(self, f"async_step_{next_step}")()

        slot_config = self.slot_configs[slot_index - 1]
        return self.async_show_form(
            step_id=f"slot_{slot_index}",
            data_schema=_build_slot_schema(slot_config),
            errors=errors,
            description_placeholders={"slot_index": str(slot_index)},
        )

    def _serialize_options(self) -> dict[str, Any]:
        return {
            **self.bridge_options.as_dict(),
            CONF_EXTERNAL_SENSOR_SLOTS: dump_slot_configs(self.slot_configs),
        }


def _build_connection_schema(defaults: Mapping[str, Any] | None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): selector.TextSelector(),
            vol.Required(
                CONF_PORT,
                default=int(defaults.get(CONF_PORT, DEFAULT_PORT)),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    mode=selector.NumberSelectorMode.BOX,
                    min=1,
                    max=65535,
                    step=1,
                )
            ),
            vol.Required(
                CONF_UNIT_ID,
                default=int(defaults.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    mode=selector.NumberSelectorMode.BOX,
                    min=1,
                    max=247,
                    step=1,
                )
            ),
            vol.Required(
                CONF_PROFILE_MODE,
                default=defaults.get(CONF_PROFILE_MODE, PROFILE_MODE_AUTO),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[PROFILE_MODE_AUTO, PROFILE_FUTURA_LMS, PROFILE_FUTURA_LP],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_SCAN_INTERVAL_S,
                default=int(defaults.get(CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S)),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    mode=selector.NumberSelectorMode.BOX,
                    min=5,
                    step=1,
                )
            ),
        }
    )


def _build_slot_schema(slot_config: ExternalSensorSlotConfig) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ENABLED, default=slot_config.enabled): selector.BooleanSelector(),
            vol.Optional(CONF_SLOT_NAME, default=slot_config.slot_name): selector.TextSelector(),
            vol.Optional(
                CONF_TEMPERATURE_ENTITY_ID,
                description={"suggested_value": slot_config.temperature_entity_id},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=list(ALLOWED_SOURCE_DOMAINS))
            ),
            vol.Optional(
                CONF_HUMIDITY_ENTITY_ID,
                description={"suggested_value": slot_config.humidity_entity_id},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=list(ALLOWED_SOURCE_DOMAINS))
            ),
            vol.Optional(
                CONF_CO2_ENTITY_ID,
                description={"suggested_value": slot_config.co2_entity_id},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=list(ALLOWED_SOURCE_DOMAINS))
            ),
            vol.Optional(
                CONF_FLOOR_TEMPERATURE_ENTITY_ID,
                description={"suggested_value": slot_config.floor_temperature_entity_id},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=list(ALLOWED_SOURCE_DOMAINS))
            ),
        }
    )


async def _async_validate_user_connection(user_input: dict[str, Any]) -> Any:
    host = str(user_input[CONF_HOST]).strip()
    if not host:
        raise CannotConnectError

    port = int(user_input[CONF_PORT])
    unit_id = int(user_input[CONF_UNIT_ID])
    scan_interval = int(user_input[CONF_SCAN_INTERVAL_S])
    if port < 1 or port > 65535 or unit_id < 1 or unit_id > 247 or scan_interval < 5:
        raise CannotConnectError

    return await async_validate_connection(
        host=host,
        port=port,
        unit_id=unit_id,
        profile_mode=str(user_input[CONF_PROFILE_MODE]),
    )


async def _async_validate_slot(
    hass: Any, user_input: dict[str, Any]
) -> dict[str, str]:
    errors: dict[str, str] = {}
    enabled = bool(user_input.get(CONF_ENABLED, False))
    entity_values = [
        user_input.get(CONF_TEMPERATURE_ENTITY_ID),
        user_input.get(CONF_HUMIDITY_ENTITY_ID),
        user_input.get(CONF_CO2_ENTITY_ID),
        user_input.get(CONF_FLOOR_TEMPERATURE_ENTITY_ID),
    ]
    if enabled and not any(entity_values):
        errors["base"] = "slot_requires_source"
        return errors

    entity_registry = er.async_get(hass)
    for field_key, unit_validator in (
        (CONF_TEMPERATURE_ENTITY_ID, _is_valid_temperature_unit),
        (CONF_FLOOR_TEMPERATURE_ENTITY_ID, _is_valid_temperature_unit),
        (CONF_HUMIDITY_ENTITY_ID, _is_valid_humidity_unit),
        (CONF_CO2_ENTITY_ID, _is_valid_co2_unit),
    ):
        entity_id = user_input.get(field_key)
        if not entity_id:
            continue
        if entity_id.split(".", 1)[0] not in ALLOWED_SOURCE_DOMAINS:
            errors[field_key] = "invalid_entity_domain"
            continue

        if entity_registry.async_get(entity_id) is None and hass.states.get(entity_id) is None:
            errors[field_key] = "entity_not_found"
            continue

        state = hass.states.get(entity_id)
        if state is None:
            continue

        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if unit is not None and not unit_validator(unit):
            errors[field_key] = "invalid_entity_unit"

    return errors


def _is_valid_temperature_unit(unit: str) -> bool:
    return unit in {"°C", "C", "degC", "°F", "degF"}


def _is_valid_humidity_unit(unit: str) -> bool:
    return unit == "%"


def _is_valid_co2_unit(unit: str) -> bool:
    return unit == "ppm"
