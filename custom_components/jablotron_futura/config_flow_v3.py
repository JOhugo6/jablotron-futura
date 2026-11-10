"""Native v3 draft wizard. No writes occur before the confirmed commit."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector

from .const import DOMAIN
from . import coordinator as transport
from .identity import hardware_fingerprint, identity_token, normalize_host
from .flow_labels import LABELS as FIELD_LABELS
from .models import default_v3_options, validate_v3_options, with_source_age_default
from .validation import (
    metric_unit_is_valid,
    normalize_metric_value,
    validate_runtime_options,
)

METRICS = ("temperature", "humidity", "co2", "floor_temperature")
UNITS = {"temperature": "°C", "humidity": "%", "co2": "ppm", "floor_temperature": "°C"}
LABELS = {
    "en": {
        "continue": "Continue",
        "back": "Back",
        "cancel": "Cancel",
        "save": "Save",
        "disabled": "Disabled",
        "none": "None",
        "read": "Read",
        "ha_writeback": "HA Write-back",
        "futura": "Futura",
        "ha_control": "HA Control",
        "sensor": "Sensor",
        "button": "Button",
        "supply": "Supply",
        "exhaust": "Exhaust",
        "standalone": "Without zone",
        "yes": "Yes",
        "no": "No",
        "unchanged": "No changes",
        "unavailable": "Unavailable",
        "preview": "Read selected slots",
        "runtime": "Intervals and bridge",
        "zones": "Zones",
        "sensor_slots": "Sensors",
        "button_slots": "Buttons",
        "connection": "Connection",
        "summary": "Summary",
        "repair": "Repair archived choices",
        "full": "Full configuration",
        "keep_disabled": "Keep archived and disabled",
        "remove": "Remove from active configuration (archive retained)",
        "restore": "Restore archived choice to a free slot",
        "retain": "Keep slots without zone",
        "deactivate": "Disable associated slots",
        "accept_defaults": "Use the displayed runtime values",
        "edit_runtime": "Edit runtime settings first",
        "saved_value": "Saved value",
        "proposed_value": "Value proposed for saving",
        "saved_choice": "Saved choice",
        "invalid_runtime": "The saved setting is invalid. Temporary valid defaults are in use; you can edit them before accepting.",
        "conflicting_choice": "Saved choices conflict. Choose what to keep inactive or restore into an unused slot. Restored slots stay disabled until edited.",
        "review_choice": "This saved choice needs review before it can be used.",
        "complex_choice": "Additional original details are preserved in the migration archive for support.",
    },
    "cs": {
        "continue": "Pokračovat",
        "back": "Zpět",
        "cancel": "Zrušit",
        "save": "Uložit",
        "disabled": "Vypnuto",
        "none": "Žádný",
        "read": "Čtení",
        "ha_writeback": "HA Write-back",
        "futura": "Futura",
        "ha_control": "HA Control",
        "sensor": "Senzor",
        "button": "Tlačítko",
        "supply": "Přívod",
        "exhaust": "Odtah",
        "standalone": "Bez vazby na zónu",
        "yes": "Ano",
        "no": "Ne",
        "unchanged": "Beze změn",
        "unavailable": "Nedostupné",
        "preview": "Načíst zvolené sloty",
        "runtime": "Intervaly a bridge",
        "zones": "Zóny",
        "sensor_slots": "Senzory",
        "button_slots": "Tlačítka",
        "connection": "Připojení",
        "summary": "Souhrn",
        "repair": "Opravit archivované volby",
        "full": "Úplné nastavení",
        "keep_disabled": "Ponechat archivované a vypnuté",
        "remove": "Odstranit z aktivní konfigurace (archiv zůstává)",
        "restore": "Obnovit archivovanou volbu do volného slotu",
        "retain": "Zachovat sloty bez vazby",
        "deactivate": "Vypnout navázané sloty",
        "accept_defaults": "Použít zobrazené provozní hodnoty",
        "edit_runtime": "Nejprve upravit provozní nastavení",
        "saved_value": "Původní hodnota",
        "proposed_value": "Hodnota navržená k uložení",
        "saved_choice": "Původní volba",
        "invalid_runtime": "Uložené nastavení je neplatné. Používají se dočasné platné výchozí hodnoty; před přijetím je můžete upravit.",
        "conflicting_choice": "Uložené volby jsou v konfliktu. Vyberte, co ponechat neaktivní nebo obnovit do nepoužitého slotu. Obnovené sloty zůstanou vypnuté, dokud je neupravíte.",
        "review_choice": "Tuto uloženou volbu je před použitím nutné zkontrolovat.",
        "complex_choice": "Další původní podrobnosti jsou zachované v migračním archivu pro podporu.",
    },
}


def _select(options: list[Any], translation_key: str | None = None) -> Any:
    config = {"options": options, "mode": "dropdown"}
    if translation_key:
        config["translation_key"] = translation_key
    return selector.SelectSelector(selector.SelectSelectorConfig(**config))


def _number(minimum: int, maximum: int, unit: str | None = None) -> Any:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode="box",
            **({"unit_of_measurement": unit} if unit else {}),
        )
    )


def _optional(schema: dict, key: str, value: Any, control: Any) -> None:
    schema[vol.Optional(key, description={"suggested_value": value})] = control


def _entry_identity(data: dict[str, Any]) -> dict[str, Any]:
    return dict(data.get("device_identity", data))


def _integers(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: int(value) if isinstance(value, float) and value.is_integer() else value
        for key, value in values.items()
    }


def source_error(
    hass: Any, entity_id: str, metric: str, assumption: str | None
) -> str | None:
    """Apply shared validation to states and unavailable registry metadata."""
    if entity_id.partition(".")[0] not in {"sensor", "number", "input_number"}:
        return "invalid_entity_domain"
    state = hass.states.get(entity_id)
    registered = er.async_get(hass).async_get(entity_id)
    if state is None and registered is None:
        return "entity_not_found"
    unit = state.attributes.get("unit_of_measurement") if state else None
    if unit is None and registered is not None:
        unit = getattr(registered, "unit_of_measurement", None)
        if unit is None:
            unit = (getattr(registered, "capabilities", None) or {}).get(
                "unit_of_measurement"
            )
    if not metric_unit_is_valid(metric, unit, assumption):
        return "unitless_confirmation_required" if not unit else "invalid_entity_unit"
    if (
        state is not None
        and state.state not in {"unknown", "unavailable"}
        and normalize_metric_value(metric, state.state, unit, assumption) is None
    ):
        return "invalid_source_value"
    return None


def repair_choices(options: dict) -> list[dict]:
    """Expose every conflicting choice, including each colliding button and floor source."""
    choices = []
    for conflict in options.get("migration_archive", {}).get("conflicts", []):
        value = conflict.get("value")
        values = value if isinstance(value, list) else [value]
        for candidate in values:
            if (
                isinstance(candidate, dict)
                and candidate
                and all(isinstance(row, dict) for row in candidate.values())
                and all(str(key).isdigit() for key in candidate)
            ):
                values_to_add = list(candidate.values())
            else:
                values_to_add = [candidate]
            for row in values_to_add:
                choices.append({**conflict, "value": deepcopy(row)})
    return choices or [
        {
            "field": "configuration",
            "error": "review_original_configuration",
            "value": None,
        }
    ]


def repair_kind(conflict: dict) -> str | None:
    """Identify one destination kind without discarding contradictory semantics."""
    kinds = set()
    field = conflict.get("field", "").split(".")[0]
    if field in {"sensor_slots", "button_slots"}:
        kinds.add(field)
    raw = conflict.get("value")
    if isinstance(raw, dict):
        if set(raw) & {
            "mode",
            "sensor_mode",
            "writeback_enabled",
            "unitless_assumptions",
            *(f"{metric}_entity_id" for metric in METRICS),
        }:
            kinds.add("sensor_slots")
        if set(raw) & {
            "ownership",
            "ext_button_mode",
            "button_mode",
            "default_timer_seconds",
            "max_active_seconds",
            "button_configs",
        }:
            kinds.add("button_slots")
    return next(iter(kinds)) if len(kinds) == 1 else None


def slot_is_unused(slot: dict, group: str, index: str) -> bool:
    """None/disabled is not empty: retained user choices must not be displaced."""
    default = default_v3_options()[group][index]
    return {
        key: value for key, value in slot.items() if key != "entity_identity_suffix"
    } == {
        key: value for key, value in default.items() if key != "entity_identity_suffix"
    }


def restore_choice(default: dict, conflict: dict, group: str) -> dict:
    """Translate archived field names once for an explicit UI restoration."""
    candidate = deepcopy(default)
    kind = repair_kind(conflict)
    if kind is None:
        raise ValueError("repair_use_editor")
    if group != kind:
        raise ValueError("repair_kind_mismatch")
    raw = conflict.get("value")
    field = conflict.get("field", "").split(".")[-1]
    if not isinstance(raw, dict):
        if (
            group == "sensor_slots"
            and field.endswith("_entity_id")
            and isinstance(raw, str)
        ):
            raw = {field: raw, "mode": "ha_writeback"}
        else:
            raise ValueError("repair_use_editor")
    aliases = {
        "slot_name": "name",
        "zone_name": "name",
        "sensor_mode": "mode",
        "ext_button_mode": "ownership",
        "zone_enabled": "enabled",
    }
    for key, value in raw.items():
        key = aliases.get(key, key)
        if key == "writeback_enabled":
            if type(value) is not bool:
                raise ValueError("repair_use_editor")
            candidate["mode"] = "ha_writeback" if value else "none"
            continue
        if key not in candidate and key not in {
            "slot_index",
            "button_id",
            "button_index",
            "zone_index",
        }:
            raise ValueError("repair_use_editor")
        if key in candidate and key not in {"enabled", "entity_identity_suffix"}:
            candidate[key] = deepcopy(value)
    # Free-slot destination has its own stable identity. The archive retains aliases.
    candidate["enabled"] = False
    return candidate


class V3Wizard:
    """Shared private draft editor for initial setup, reconfigure and options."""

    def _initialize(self, entry: Any = None, *, lightweight: bool = False) -> None:
        self._entry = entry
        self._lightweight = lightweight
        self._draft = (
            with_source_age_default(entry.options) if entry else default_v3_options()
        )
        self._original = deepcopy(self._draft)
        self._connection = {
            "host": "",
            "port": 502,
            "unit_id": 1,
            "profile_mode": "auto",
        }
        if entry:
            self._connection.update(
                {
                    key: entry.data.get(key, value)
                    for key, value in self._connection.items()
                }
            )
        self._validation = None
        self._selected = "1"
        self._zone_key = "supply_1"
        self._pending_zone = None
        self._sensor_candidate = None
        self._button_candidate = None
        self._repair_index = 0
        self._repair_runtime_edit = False
        self._preview_result = {}
        self._baseline_initialized = entry is not None
        self._bindings_proposed = entry is not None
        self._edited_bindings: set[tuple[str, str]] = set()

    def _t(self, key: str) -> str:
        language = getattr(self, "_language", None) or getattr(self, "context", {}).get(
            "language", getattr(self.hass.config, "language", "en")
        )
        language = "cs" if str(language).startswith("cs") else "en"
        return LABELS[language].get(key, FIELD_LABELS[language].get(key, key))

    def _actions(self, choices: tuple[str, ...], default: str = "continue") -> dict:
        return {
            vol.Required("action", default=default): _select(
                list(choices), "wizard_action"
            )
        }

    def _texts(self, **renderers: Any) -> dict[str, str]:
        return {key: render() for key, render in renderers.items()}

    async def _load_language(self) -> None:
        """Use this authenticated user's frontend language for dynamic summaries."""
        from homeassistant.helpers.http import current_request

        request = current_request.get()
        if request is not None and (user := request.get("hass_user")) is not None:
            from homeassistant.components.frontend.storage import async_user_store

            store = await async_user_store(self.hass, user.id)
            self._language = store.data.get("language", {}).get("language")

    def _form(
        self, step: str, schema: dict, errors: dict | None = None, **placeholders: str
    ) -> dict:
        return self.async_show_form(
            step_id=step,
            data_schema=vol.Schema(schema),
            errors=errors or {},
            description_placeholders=placeholders,
        )

    async def _route(self, action: str) -> dict:
        if action == "cancel":
            return self.async_abort(reason="cancelled")
        return await getattr(self, f"async_step_{action}")()

    async def _probe(self) -> Any:
        return await transport.async_validate_connection(**self._connection)

    def _duplicate(self, validation: Any) -> bool:
        fingerprint = hardware_fingerprint(validation.identity.as_dict())
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if self._entry and entry.entry_id == self._entry.entry_id:
                continue
            if (
                normalize_host(str(entry.data.get("host", ""))),
                entry.data.get("port", 502),
                entry.data.get("unit_id", 1),
            ) == (normalize_host(validation.host), validation.port, validation.unit_id):
                return True
            try:
                if fingerprint == hardware_fingerprint(_entry_identity(entry.data)):
                    return True
            except ValueError:
                continue
        return False

    async def async_step_connection(self, user_input: dict | None = None) -> dict:
        await self._load_language()
        errors = {}
        if user_input is not None:
            if user_input.get("action") == "cancel":
                return await self._route("cancel")
            values = _integers(user_input)
            self._connection.update(
                {key: values[key] for key in self._connection if key in values}
            )
            self._connection["host"] = normalize_host(self._connection["host"])
            if not self._connection["host"]:
                errors["host"] = "cannot_connect"
            for key, maximum in (("port", 65535), ("unit_id", 247)):
                if (
                    type(self._connection[key]) is not int
                    or not 1 <= self._connection[key] <= maximum
                ):
                    errors[key] = "invalid_value"
            if not errors:
                try:
                    validation = await self._probe()
                    if self._duplicate(validation):
                        return self.async_abort(reason="already_configured")
                    if self._entry and hardware_fingerprint(
                        _entry_identity(self._entry.data)
                    ) != hardware_fingerprint(validation.identity.as_dict()):
                        errors["base"] = "identity_mismatch"
                    else:
                        self._validation = validation
                        if not self._entry and not self._baseline_initialized:
                            self._discover_zones(validation.topology_snapshot)
                            self._original = deepcopy(self._draft)
                            self._baseline_initialized = True
                        return await self.async_step_device_info()
                except (
                    transport.CannotConnectError,
                    transport.IncompleteIdentityError,
                    transport.InvalidProfileError,
                    transport.NotFuturaDeviceError,
                ) as err:
                    errors["base"] = _connection_error(err)
        return self._form(
            "connection",
            {
                vol.Required(
                    "host", default=self._connection["host"]
                ): selector.TextSelector(),
                vol.Required("port", default=self._connection["port"]): _number(
                    1, 65535
                ),
                vol.Required("unit_id", default=self._connection["unit_id"]): _number(
                    1, 247
                ),
                vol.Required(
                    "profile_mode", default=self._connection["profile_mode"]
                ): _select(["auto", "futura_lms"], "profile_mode"),
                **self._actions(("continue", "cancel")),
            },
            errors,
        )

    def _discover_zones(self, topology: dict) -> None:
        for zone in topology.get("zones", []):
            index = zone.get("zone_index")
            for kind in ("supply", "exhaust"):
                key = f"{kind}_{index}"
                if key not in self._draft["zones"]:
                    continue
                target = self._draft["zones"][key]
                for field in (
                    "supply_damper_ids",
                    "exhaust_damper_ids",
                    "button_ids",
                    "alfa_index",
                ):
                    if field in zone:
                        target[field] = deepcopy(zone[field])
                target["enabled"] = bool(
                    zone.get(f"{kind}_damper_ids")
                    or (
                        zone.get("alfa_index")
                        if kind == "supply"
                        else zone.get("button_ids")
                    )
                )
                target["name"] = f"{self._t(kind)} {index}"

    def _topology_changes(self) -> str:
        if not self._entry:
            return self._t("none")
        discovered = {
            str(zone["zone_index"]): zone
            for zone in self._validation.topology_snapshot.get("zones", [])
        }
        differences = []
        for key, saved in self._draft["zones"].items():
            side, index = key.split("_")
            current = discovered.get(index, {})
            fields = (
                f"{side}_damper_ids",
                "alfa_index" if side == "supply" else "button_ids",
            )
            for field in fields:
                before = saved.get(field)
                after = current.get(field, None if field == "alfa_index" else [])
                if before != after:
                    differences.append(
                        f"{self._zone_label(key)} · {self._t(field)}: {before} → {after}"
                    )
        return "\n\n".join(differences) or self._t("unchanged")

    async def async_step_device_info(self, user_input: dict | None = None) -> dict:
        detected = bool(self._validation.fut_config_raw & (1 << 4))
        if user_input:
            if user_input.get("action") in {"back", "cancel"}:
                return await self._route(
                    "connection" if user_input["action"] == "back" else "cancel"
                )
            self._draft["variobreeze"] = user_input["variobreeze"]
            if not self._bindings_proposed and self._draft["variobreeze"]:
                for group, kind in (
                    ("sensor_slots", "supply"),
                    ("button_slots", "exhaust"),
                ):
                    for key, slot in self._draft[group].items():
                        if (group, key) not in self._edited_bindings and self._draft[
                            "zones"
                        ][f"{kind}_{key}"]["enabled"]:
                            slot["zone_binding"] = f"{kind}_{key}"
                self._bindings_proposed = True
            if self._draft.get("migration_needs_repair"):
                return await self.async_step_repair()
            if self._draft["variobreeze"] != detected:
                return await self.async_step_setup_warning()
            return await self._route(
                "zones" if self._draft["variobreeze"] else "sensor_slots"
            )
        identity = self._validation.identity.as_dict()
        return self._form(
            "device_info",
            {
                vol.Required(
                    "variobreeze", default=self._draft.get("variobreeze", detected)
                ): selector.BooleanSelector(),
                **self._actions(("continue", "back", "cancel")),
            },
            **self._texts(
                identity=lambda: self._format_values(identity),
                detected=lambda: self._t("yes" if detected else "no"),
                topology_changes=self._topology_changes,
            ),
        )

    async def async_step_setup_warning(self, user_input: dict | None = None) -> dict:
        if user_input:
            if user_input["action"] == "back":
                return await self.async_step_device_info()
            return await self._route(
                "zones" if self._draft["variobreeze"] else "sensor_slots"
            )
        return self._form("setup_warning", self._actions(("continue", "back")))

    async def async_step_zones(self, user_input: dict | None = None) -> dict:
        if user_input:
            action = user_input["action"]
            if action == "continue":
                return await self._route("summary" if self._lightweight else "preview")
            if action == "back":
                return await self._route("init" if self._lightweight else "device_info")
            if action == "cancel":
                return await self._route(action)
            self._zone_key = action
            return await self.async_step_zone_detail()
        choices = [*self._draft["zones"], "continue", "back", "cancel"]
        return self._form(
            "zones",
            {
                vol.Required("action", default="continue"): _select(
                    choices, "zone_action"
                )
            },
            **self._texts(
                zones=lambda: "\n\n".join(
                    f"{self._zone_label(key)} · {zone['name']} · {self._t('yes' if zone['enabled'] else 'disabled')}"
                    for key, zone in self._draft["zones"].items()
                )
            ),
        )

    def _zone_label(self, key: str) -> str:
        side, index = key.split("_")
        return f"{self._t(side)} {index}"

    async def async_step_zone_detail(self, user_input: dict | None = None) -> dict:
        zone = self._draft["zones"][self._zone_key]
        errors = {}
        if user_input:
            if user_input.get("action") == "back":
                return await self.async_step_zones()
            candidate = deepcopy(zone)
            candidate.update(
                {
                    key: user_input[key]
                    for key in ("name", "enabled")
                    if key in user_input
                }
            )
            candidate["area_id"] = user_input.get("area_id") or None
            if candidate["area_id"]:
                from homeassistant.helpers import area_registry as ar

                if ar.async_get(self.hass).async_get_area(candidate["area_id"]) is None:
                    errors["area_id"] = "invalid_value"
            if not str(candidate["name"]).strip():
                errors["name"] = "invalid_value"
            side = self._zone_key.split("_")[0]
            for index in zone.get(f"{side}_damper_ids", []):
                candidate.setdefault("damper_names", {}).pop(str(index), None)
            for key, value in user_input.items():
                if key.startswith("damper_"):
                    candidate.setdefault("damper_names", {})[
                        key.removeprefix("damper_")
                    ] = value
            if not errors:
                linked = any(
                    slot.get("zone_binding") == self._zone_key
                    for group in ("sensor_slots", "button_slots")
                    for slot in self._draft[group].values()
                )
                if (
                    not self._lightweight
                    and zone["enabled"]
                    and not candidate["enabled"]
                    and linked
                ):
                    self._pending_zone = candidate
                    return await self.async_step_zone_disabled()
                self._draft["zones"][self._zone_key] = candidate
                return await self.async_step_zones()
        schema = {vol.Required("name", default=zone["name"]): selector.TextSelector()}
        if not self._lightweight:
            schema[vol.Required("enabled", default=zone["enabled"])] = (
                selector.BooleanSelector()
            )
        _optional(schema, "area_id", zone.get("area_id"), selector.AreaSelector())
        side = self._zone_key.split("_")[0]
        for index in zone.get(f"{side}_damper_ids", []):
            _optional(
                schema,
                f"damper_{index}",
                zone.get("damper_names", {}).get(str(index), ""),
                selector.TextSelector(),
            )
        schema.update(self._actions(("continue", "back")))
        return self._form(
            "zone_detail",
            schema,
            errors,
            zone=zone["name"],
            topology=self._format_values(
                {
                    key: zone.get(key)
                    for key in (
                        "supply_damper_ids",
                        "exhaust_damper_ids",
                        "alfa_index",
                        "button_ids",
                    )
                }
            ),
        )

    async def async_step_zone_disabled(self, user_input: dict | None = None) -> dict:
        if user_input:
            if user_input["action"] == "back":
                return await self.async_step_zone_detail()
            for group in ("sensor_slots", "button_slots"):
                for slot in self._draft[group].values():
                    if slot.get("zone_binding") == self._zone_key:
                        if user_input["action"] == "deactivate":
                            slot["enabled"] = False
                        else:
                            slot["zone_binding"] = None
            self._draft["zones"][self._zone_key] = self._pending_zone
            return await self.async_step_zones()
        return self._form(
            "zone_disabled", self._actions(("retain", "deactivate", "back"), "retain")
        )

    async def async_step_preview(self, user_input: dict | None = None) -> dict:
        errors = {}
        if user_input:
            action = user_input["action"]
            if action == "continue":
                return await self.async_step_sensor_slots()
            if action == "back":
                return await self.async_step_zones()
            if action == "preview":
                try:
                    self._preview_result = await transport.async_preview_slots(
                        **self._connection,
                        sensor_slots=[
                            int(key)
                            for key, slot in self._draft["sensor_slots"].items()
                            if slot["enabled"] and slot["mode"] != "none"
                        ],
                        button_slots=[
                            int(key)
                            for key, slot in self._draft["button_slots"].items()
                            if slot["enabled"] and slot["ownership"] != "none"
                        ],
                    )
                except (
                    transport.CannotConnectError,
                    transport.IncompleteIdentityError,
                    transport.InvalidProfileError,
                    transport.NotFuturaDeviceError,
                ) as err:
                    errors["base"] = _connection_error(err)
        alfa = {
            str(zone["alfa_index"]): zone.get("alfa_live_values", {})
            for zone in self._validation.topology_snapshot.get("zones", [])
            if zone.get("alfa_index") is not None
        }
        return self._form(
            "preview",
            self._actions(("continue", "preview", "back")),
            errors,
            **self._texts(
                readings=lambda: self._readings(self._preview_result),
                alfa=lambda: self._format_values(alfa),
            ),
        )

    def _readings(self, values: dict) -> str:
        rows = []
        for group in ("sensor_slots", "button_slots"):
            for index, snapshot in values.get(group, {}).items():
                if group == "button_slots" and isinstance(snapshot, dict):
                    snapshot = dict(snapshot)
                    if "mode" in snapshot:
                        mode = snapshot.pop("mode")
                        snapshot["button_mode"] = {0: "boost", 1: "digestor"}.get(
                            mode, mode
                        )
                rows.append(
                    f"**{self._t('sensor' if group == 'sensor_slots' else 'button')} {index}**\n{self._format_values(snapshot)}"
                )
        return "\n\n".join(rows) or self._t("none")

    def _format_values(self, value: Any) -> str:
        if isinstance(value, dict):
            units = {**UNITS, "ntc_temperature": "°C", "remaining_seconds": "s"}
            return "\n\n".join(
                f"{self._t(key)}: {self._format_values(item)}"
                + (
                    f" {units[key]}"
                    if key in units and type(item) in (int, float)
                    else ""
                )
                for key, item in value.items()
            )
        if value is None:
            return self._t("unavailable")
        if type(value) is bool:
            return self._t("yes" if value else "no")
        return self._t(value) if isinstance(value, str) else str(value)

    async def _slot_list(self, group: str, user_input: dict | None) -> dict:
        if user_input:
            action = user_input["action"]
            if action == "continue":
                return await self._route(
                    "summary"
                    if self._lightweight or group == "button_slots"
                    else "button_slots"
                )
            if action == "back":
                return await self._route(
                    "init"
                    if self._lightweight
                    else (
                        "sensor_slots"
                        if group == "button_slots"
                        else (
                            "preview"
                            if self._draft.get("variobreeze")
                            else "device_info"
                        )
                    )
                )
            if action == "cancel":
                return await self._route(action)
            self._selected = action
            self._sensor_candidate = None
            self._button_candidate = None
            return await self._route(
                "sensor_detail" if group == "sensor_slots" else "button_detail"
            )
        mode = "mode" if group == "sensor_slots" else "ownership"
        choices = [*self._draft[group], "continue", "back", "cancel"]
        return self._form(
            group,
            {
                vol.Required("action", default="continue"): _select(
                    choices, "slot_action"
                )
            },
            **self._texts(
                slots=lambda: "\n\n".join(
                    f"**{key} · {slot['name']}** · {self._t(slot[mode])} · {self._t('disabled') if not slot['enabled'] else (self._zone_label(slot['zone_binding']) if slot.get('zone_binding') else self._t('standalone'))}"
                    for key, slot in self._draft[group].items()
                )
            ),
        )

    async def async_step_sensor_slots(self, user_input: dict | None = None) -> dict:
        return await self._slot_list("sensor_slots", user_input)

    async def async_step_button_slots(self, user_input: dict | None = None) -> dict:
        return await self._slot_list("button_slots", user_input)

    def _binding(self, kind: str, current: str | None) -> Any:
        return _select(
            [{"value": "none", "label": self._t("standalone")}]
            + [
                {"value": key, "label": f"{key.split('_')[1]} · {zone['name']}"}
                for key, zone in self._draft["zones"].items()
                if key.startswith(kind) and (zone["enabled"] or key == current)
            ]
        )

    async def async_step_sensor_detail(self, user_input: dict | None = None) -> dict:
        slot = self._sensor_candidate or deepcopy(
            self._draft["sensor_slots"][self._selected]
        )
        errors = {}
        if user_input:
            if user_input.get("action") == "back":
                return await self.async_step_sensor_slots()
            slot.update(
                {
                    key: user_input[key]
                    for key in ("name", "enabled", "mode")
                    if key in user_input
                }
            )
            if not self._lightweight:
                slot["zone_binding"] = (
                    None
                    if user_input.get("zone_binding") in (None, "", "none")
                    else user_input["zone_binding"]
                )
            if not str(slot["name"]).strip():
                errors["name"] = "invalid_value"
            else:
                self._sensor_candidate = slot
                if not self._lightweight:
                    self._edited_bindings.add(("sensor_slots", self._selected))
                if self._lightweight or not slot["enabled"] or slot["mode"] == "none":
                    self._draft["sensor_slots"][self._selected] = slot
                    return await self.async_step_sensor_slots()
                return await self._route(
                    "sensor_sources"
                    if slot["mode"] == "ha_writeback"
                    else "sensor_readback"
                )
        schema = {vol.Required("name", default=slot["name"]): selector.TextSelector()}
        if not self._lightweight:
            schema.update(
                {
                    vol.Required(
                        "enabled", default=slot["enabled"]
                    ): selector.BooleanSelector(),
                    vol.Required("mode", default=slot["mode"]): _select(
                        ["none", "read", "ha_writeback"], "sensor_mode"
                    ),
                    vol.Optional(
                        "zone_binding", default=slot.get("zone_binding") or "none"
                    ): self._binding("supply", slot.get("zone_binding")),
                }
            )
        schema.update(self._actions(("continue", "back")))
        return self._form("sensor_detail", schema, errors, slot=self._selected)

    async def async_step_sensor_sources(self, user_input: dict | None = None) -> dict:
        slot = self._sensor_candidate
        errors = {}
        if user_input:
            if user_input.get("action") == "back":
                return await self.async_step_sensor_detail()
            for metric in METRICS:
                field = f"{metric}_entity_id"
                slot[field] = user_input.get(field) or None
                old = self._draft["sensor_slots"][self._selected]
                assumption = (
                    old.get("unitless_assumptions", {}).get(metric)
                    if old.get(field) == slot[field]
                    else None
                )
                if f"{metric}_unitless" in user_input:
                    assumption = None
                if user_input.get(f"{metric}_unitless"):
                    assumption = UNITS[metric]
                slot.setdefault("unitless_assumptions", {})[metric] = assumption
                if slot[field]:
                    error = source_error(self.hass, slot[field], metric, assumption)
                    if error:
                        errors[field] = error
            if not any(slot.get(f"{metric}_entity_id") for metric in METRICS):
                errors["base"] = "writeback_entities_required"
            if not errors:
                self._draft["sensor_slots"][self._selected] = deepcopy(slot)
                return await self.async_step_sensor_slots()
        schema = {}
        for metric in METRICS:
            _optional(
                schema,
                f"{metric}_entity_id",
                slot.get(f"{metric}_entity_id"),
                selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "number", "input_number"]
                    )
                ),
            )
            schema[
                vol.Optional(
                    f"{metric}_unitless",
                    default=bool(slot.get("unitless_assumptions", {}).get(metric)),
                )
            ] = selector.BooleanSelector()
        schema.update(self._actions(("continue", "back")))
        return self._form("sensor_sources", schema, errors, slot=self._selected)

    async def _readback(self, group: str, user_input: dict | None) -> dict:
        kind = "sensor" if group == "sensor_slots" else "button"
        if user_input and user_input["action"] == "back":
            return await self._route(f"{kind}_detail")
        if user_input and user_input["action"] == "continue":
            self._draft[group][self._selected] = deepcopy(
                getattr(self, f"_{kind}_candidate")
            )
            return await self._route(group)
        errors, readings = {}, {}
        try:
            readings = await transport.async_preview_slots(
                **self._connection,
                sensor_slots=[int(self._selected)] if kind == "sensor" else [],
                button_slots=[int(self._selected)] if kind == "button" else [],
            )
        except (
            transport.CannotConnectError,
            transport.IncompleteIdentityError,
            transport.InvalidProfileError,
            transport.NotFuturaDeviceError,
        ) as err:
            errors["base"] = _connection_error(err)
        return self._form(
            f"{kind}_readback",
            self._actions(("continue", "preview", "back")),
            errors,
            slot=self._selected,
            **self._texts(readings=lambda: self._readings(readings)),
        )

    async def async_step_sensor_readback(self, user_input: dict | None = None) -> dict:
        return await self._readback("sensor_slots", user_input)

    async def async_step_button_readback(self, user_input: dict | None = None) -> dict:
        return await self._readback("button_slots", user_input)

    async def async_step_button_detail(self, user_input: dict | None = None) -> dict:
        slot = self._button_candidate or deepcopy(
            self._draft["button_slots"][self._selected]
        )
        errors = {}
        if user_input:
            if user_input.get("action") == "back":
                return await self.async_step_button_slots()
            slot.update(
                {
                    key: user_input[key]
                    for key in ("name", "enabled", "ownership")
                    if key in user_input
                }
            )
            if not self._lightweight:
                slot["zone_binding"] = (
                    None
                    if user_input.get("zone_binding") in (None, "", "none")
                    else user_input["zone_binding"]
                )
            if not str(slot["name"]).strip():
                errors["name"] = "invalid_value"
            else:
                self._button_candidate = slot
                if not self._lightweight:
                    self._edited_bindings.add(("button_slots", self._selected))
                if not slot["enabled"] or slot["ownership"] != "ha_control":
                    self._draft["button_recovery_requests"] = [
                        key
                        for key in self._draft.get("button_recovery_requests", [])
                        if key != self._selected
                    ]
                if slot["enabled"] and slot["ownership"] == "ha_control":
                    return await self.async_step_button_action()
                if (
                    not self._lightweight
                    and slot["enabled"]
                    and slot["ownership"] == "futura"
                ):
                    return await self.async_step_button_readback()
                self._draft["button_slots"][self._selected] = slot
                return await self.async_step_button_slots()
        schema = {vol.Required("name", default=slot["name"]): selector.TextSelector()}
        if not self._lightweight:
            schema.update(
                {
                    vol.Required(
                        "enabled", default=slot["enabled"]
                    ): selector.BooleanSelector(),
                    vol.Required("ownership", default=slot["ownership"]): _select(
                        ["none", "futura", "ha_control"], "button_ownership"
                    ),
                    vol.Optional(
                        "zone_binding", default=slot.get("zone_binding") or "none"
                    ): self._binding("exhaust", slot.get("zone_binding")),
                }
            )
        schema.update(self._actions(("continue", "back")))
        return self._form("button_detail", schema, errors, slot=self._selected)

    async def async_step_button_action(self, user_input: dict | None = None) -> dict:
        slot = self._button_candidate
        if user_input:
            if user_input["action"] == "back":
                return await self.async_step_button_detail()
            mode = user_input["button_mode"]
            if mode != slot["button_mode"]:
                slot["default_timer_seconds"] = 300 if mode == "digestor" else 180
            slot["button_mode"] = mode
            return await self.async_step_button_timer()
        return self._form(
            "button_action",
            {
                vol.Required("button_mode", default=slot["button_mode"]): _select(
                    ["boost", "digestor"], "button_mode"
                ),
                **self._actions(("continue", "back")),
            },
            slot=self._selected,
        )

    async def async_step_button_timer(self, user_input: dict | None = None) -> dict:
        slot = self._button_candidate
        errors = {}
        recovery_failed = False
        if self._entry and not self._lightweight:
            runtime = getattr(self._entry, "runtime_data", None)
            coordinator = getattr(runtime, "coordinator", None)
            states = getattr(getattr(coordinator, "buttons", None), "states", None)
            if states is None:
                from homeassistant.helpers.storage import Store

                saved = (
                    await Store(
                        self.hass, 1, f"jablotron_futura.{self._entry.entry_id}.runtime"
                    ).async_load()
                    or {}
                )
                states = saved.get("button_recovery", {})
            recovery_failed = (
                states.get(self._selected, {}).get("state") == "cleanup_failed"
            )
        if user_input:
            if user_input["action"] == "back":
                return await self.async_step_button_action()
            values = _integers(user_input)
            for key in ("default_timer_seconds", "max_active_seconds"):
                value = values.get(key)
                if type(value) is not int or not 1 <= value <= 10800:
                    errors[key] = "invalid_value"
                else:
                    slot[key] = value
            if (
                not errors
                and slot["default_timer_seconds"] > slot["max_active_seconds"]
            ):
                errors["default_timer_seconds"] = "timer_exceeds_maximum"
            if not errors:
                self._draft["button_slots"][self._selected] = deepcopy(slot)
                if recovery_failed and user_input.get("recover_cleanup"):
                    requests = self._draft.setdefault("button_recovery_requests", [])
                    if self._selected not in requests:
                        requests.append(self._selected)
                else:
                    self._draft["button_recovery_requests"] = [
                        key
                        for key in self._draft.get("button_recovery_requests", [])
                        if key != self._selected
                    ]
                return await self.async_step_button_slots()
        schema = {
            vol.Required(key, default=slot[key]): _number(1, 10800, "s")
            for key in ("default_timer_seconds", "max_active_seconds")
        }
        if recovery_failed:
            schema[vol.Optional("recover_cleanup", default=False)] = (
                selector.BooleanSelector()
            )
        schema.update(self._actions(("continue", "back")))
        return self._form("button_timer", schema, errors, slot=self._selected)

    async def async_step_runtime(self, user_input: dict | None = None) -> dict:
        runtime = self._draft["runtime"]
        errors = {}
        if user_input:
            if user_input.get("action") == "back":
                if self._repair_runtime_edit:
                    self._repair_runtime_edit = False
                    return await self.async_step_repair()
                return await self._route("init" if self._lightweight else "summary")
            candidate = _integers(
                {key: user_input.get(key, runtime[key]) for key in runtime}
            )
            errors = validate_runtime_options(candidate)
            if not errors:
                self._draft["runtime"] = candidate
                if self._repair_runtime_edit:
                    self._repair_runtime_edit = False
                    return await self.async_step_repair()
                return await self.async_step_summary()
            runtime = candidate
        schema = {
            vol.Required(key, default=runtime[key]): selector.BooleanSelector()
            for key in ("bridge_enabled", "write_on_change_only")
        }
        for key, minimum, maximum, unit in (
            ("read_interval_ms", 1000, 86400000, "ms"),
            ("write_interval_ms", 5000, 86400000, "ms"),
            ("scan_interval_s", 5, 86400, "s"),
            ("stale_after_s", 1, 86400, "s"),
            ("force_resync_every_s", 1, 86400, "s"),
        ):
            schema[vol.Required(key, default=runtime[key])] = _number(
                minimum, maximum, unit
            )
        schema[
            vol.Required("log_level_bridge", default=runtime["log_level_bridge"])
        ] = _select(["normal", "debug"], "log_level_bridge")
        schema.update(self._actions(("continue", "back")))
        return self._form("runtime", schema, errors)

    def _repair_details(self, conflict: dict) -> tuple[str, str, str]:
        """Summarize the current decision; never put the entire support archive here."""
        path = conflict.get("field", "").split(".")
        raw = conflict.get("value")
        if path[0] == "runtime" and len(path) > 1:
            field = path[1]
            unit = (
                " ms" if field.endswith("_ms") else " s" if field.endswith("_s") else ""
            )
            old = (
                self._format_values(raw)
                if not isinstance(raw, (dict, list))
                else self._t("complex_choice")
            )
            current = self._format_values(self._draft["runtime"].get(field))
            original = f"{old}{unit}" if type(raw) in (int, float) else f"“{old}”"
            details = f"- {self._t('saved_value')}: {original}\n- {self._t('proposed_value')}: **{current}{unit}**"
            return self._t(field), details, self._t("invalid_runtime")
        kind = repair_kind(conflict)
        title = (
            self._t("sensor" if kind == "sensor_slots" else "button")
            if kind
            else self._t("saved_choice")
        )
        if len(path) > 1 and path[1].isdigit():
            title += f" · {path[1]}"
        aliases = {
            "slot_name": "name",
            "zone_name": "name",
            "sensor_mode": "mode",
            "ext_button_mode": "ownership",
        }
        if isinstance(raw, dict):
            known = {
                "name",
                "mode",
                "ownership",
                "button_mode",
                "default_timer_seconds",
                "max_active_seconds",
                "zone_binding",
                *(f"{metric}_entity_id" for metric in METRICS),
            }
            rows = [
                f"- {self._t(aliases.get(key, key))}: {self._format_values(value)}"
                for key, value in raw.items()
                if aliases.get(key, key) in known and value is not None
            ]
            details = "\n".join(rows) or self._t("complex_choice")
        else:
            details = (
                f"- {self._t(path[-1]) if path[-1] in FIELD_LABELS['en'] else self._t('saved_value')}: {self._format_values(raw)}"
                if not isinstance(raw, list)
                else self._t("complex_choice")
            )
        return (
            title,
            details,
            self._t(
                "conflicting_choice"
                if conflict.get("error")
                in {"button_collision", "conflicting_floor", "migration_conflict"}
                else "review_choice"
            ),
        )

    async def async_step_repair(self, user_input: dict | None = None) -> dict:
        conflicts = repair_choices(self._draft)
        current = conflicts[self._repair_index]
        global_conflict = current.get("field", "").startswith("runtime.")
        errors = {}
        if user_input:
            if user_input["action"] == "back":
                return await self.async_step_device_info()
            if user_input["action"] == "edit_runtime" and global_conflict:
                self._repair_runtime_edit = True
                return await self.async_step_runtime()
            if not user_input.get("confirm_resolution"):
                errors["confirm_resolution"] = "confirmation_required"
            else:
                conflict = conflicts[self._repair_index]
                if user_input["action"] == "restore":
                    group, target = user_input["target_kind"], user_input["target_slot"]
                    kind = repair_kind(conflict)
                    if kind is None:
                        errors["base"] = "repair_use_editor"
                    elif group != kind:
                        errors["target_kind"] = "repair_kind_mismatch"
                    elif target not in self._draft[group] or not slot_is_unused(
                        self._draft[group][target], group, target
                    ):
                        errors["target_slot"] = "slot_not_free"
                    else:
                        try:
                            existing = self._draft[group][target]
                            candidate = restore_choice(existing, conflict, group)
                            checked = deepcopy(self._draft)
                            checked[group][target] = candidate
                            if validate_v3_options(checked):
                                errors["base"] = "repair_use_editor"
                            else:
                                self._draft[group][target] = candidate
                        except ValueError as err:
                            errors["base"] = str(err)
                elif user_input["action"] == "remove":
                    parts = conflict.get("field", "").split(".")
                    if (
                        len(parts) >= 2
                        and parts[0] in {"sensor_slots", "button_slots"}
                        and parts[1] in self._draft[parts[0]]
                    ):
                        slot = self._draft[parts[0]][parts[1]]
                        fresh = default_v3_options()[parts[0]][parts[1]]
                        if "entity_identity_suffix" in slot:
                            fresh["entity_identity_suffix"] = slot[
                                "entity_identity_suffix"
                            ]
                        self._draft[parts[0]][parts[1]] = fresh
                if not errors:
                    self._draft.setdefault("migration_archive", {}).setdefault(
                        "resolutions", []
                    ).append(
                        {
                            "choice": self._repair_index,
                            "action": user_input["action"],
                            "target_kind": user_input.get("target_kind"),
                            "target_slot": user_input.get("target_slot"),
                        }
                    )
                    self._repair_index += 1
                    if self._repair_index >= max(1, len(conflicts)):
                        self._draft["migration_needs_repair"] = False
                        self._draft.setdefault("migration_archive", {})[
                            "resolution"
                        ] = "explicit_reconfigure"
                        return await self._route(
                            "zones"
                            if self._draft.get("variobreeze")
                            else "sensor_slots"
                        )
        conflict = conflicts[self._repair_index]
        kind = repair_kind(conflict)
        free = (
            [
                key
                for key, slot in self._draft[kind].items()
                if slot_is_unused(slot, kind, key)
            ]
            if kind
            else []
        )
        schema = self._actions(
            ("accept_defaults", "edit_runtime", "back")
            if global_conflict
            else ("keep_disabled", "remove", *(("restore",) if free else ()), "back"),
            "accept_defaults" if global_conflict else "keep_disabled",
        )
        if free:
            schema[vol.Required("target_kind", default=kind)] = _select(
                [{"value": kind, "label": self._t(kind)}]
            )
            schema[vol.Required("target_slot", default=free[0])] = _select(free)
        schema[vol.Required("confirm_resolution", default=False)] = (
            selector.BooleanSelector()
        )
        title, details, explanation = self._repair_details(conflict)
        return self._form(
            "repair",
            schema,
            errors,
            item=f"{self._repair_index + 1}/{len(conflicts)}",
            conflict_title=title,
            details=details,
            explanation=explanation,
        )

    def _summary(self) -> str:
        rows = []
        for group, mode in (("sensor_slots", "mode"), ("button_slots", "ownership")):
            for index, slot in self._draft[group].items():
                rows.append(
                    f"**{self._t('sensor' if group == 'sensor_slots' else 'button')} {index} — {slot['name']}**: {self._t(slot[mode])}; {self._t('yes' if slot['enabled'] else 'disabled')}; {slot.get('zone_binding') or self._t('standalone')}"
                )
                if group == "sensor_slots":
                    rows.extend(
                        f"{self._t(metric)}: {slot[f'{metric}_entity_id']}"
                        for metric in METRICS
                        if slot.get(f"{metric}_entity_id")
                    )
                elif slot[mode] == "ha_control":
                    rows.append(
                        f"{slot['button_mode']}: {slot['default_timer_seconds']} s / {slot['max_active_seconds']} s"
                    )
        rows.append(
            f"**{self._t('runtime')}**\n{self._format_values(self._draft['runtime'])}"
        )
        rows.append(
            f"**{self._t('zones')}**\n"
            + "\n\n".join(
                f"{zone['name']}: {self._t('yes' if zone['enabled'] else 'disabled')}; {zone.get('area_id') or self._t('none')}"
                for zone in self._draft["zones"].values()
            )
        )
        return "\n\n".join(rows)

    def _diff(self) -> str:
        rows = []

        def visit(before: Any, after: Any, path: str) -> None:
            if isinstance(before, dict) and isinstance(after, dict):
                for key in sorted(before.keys() | after.keys()):
                    if key != "migration_archive":
                        visit(
                            before.get(key), after.get(key), f"{path}.{key}".strip(".")
                        )
            elif before != after:
                label = " · ".join(self._t(part) for part in path.split("."))
                rows.append(
                    f"{label}: {self._format_values(before)} → {self._format_values(after)}"
                )

        visit(self._original, self._draft, "")
        if self._entry:
            visit(
                {key: self._entry.data.get(key) for key in self._connection},
                self._connection,
                "connection",
            )
        return "\n\n".join(rows) or self._t("unchanged")

    async def async_step_summary(self, user_input: dict | None = None) -> dict:
        errors = {}
        if user_input:
            if user_input["action"] != "save":
                return await self._route(user_input["action"])
            if not user_input.get("confirm_save"):
                errors["confirm_save"] = "confirmation_required"
            else:
                errors = (
                    {"base": "invalid_configuration"}
                    if validate_v3_options(self._draft)
                    else {}
                )
                if not errors:
                    for index, slot in self._draft["sensor_slots"].items():
                        if slot["enabled"] and slot["mode"] == "ha_writeback":
                            for metric in METRICS:
                                entity_id = slot.get(f"{metric}_entity_id")
                                if entity_id and (
                                    not self._entry
                                    or entity_id
                                    != self._original["sensor_slots"][index].get(
                                        f"{metric}_entity_id"
                                    )
                                ):
                                    if source_error(
                                        self.hass,
                                        entity_id,
                                        metric,
                                        slot.get("unitless_assumptions", {}).get(
                                            metric
                                        ),
                                    ):
                                        errors["base"] = "invalid_configuration"
                    if not errors:
                        try:
                            checked = await self._probe()
                            expected = (
                                _entry_identity(self._entry.data)
                                if self._entry
                                else self._validation.identity.as_dict()
                            )
                            if hardware_fingerprint(expected) != hardware_fingerprint(
                                checked.identity.as_dict()
                            ):
                                errors["base"] = "identity_mismatch"
                            elif self._duplicate(checked):
                                errors["base"] = "already_configured"
                            else:
                                return await self._commit(checked)
                        except (
                            transport.CannotConnectError,
                            transport.IncompleteIdentityError,
                            transport.InvalidProfileError,
                            transport.NotFuturaDeviceError,
                        ) as err:
                            errors["base"] = _connection_error(err)
                        except ValueError as err:
                            errors["base"] = (
                                str(err)
                                if str(err) in {"save_failed", "transition_failed"}
                                else "invalid_configuration"
                            )
        actions = (
            "save",
            "zones",
            "sensor_slots",
            "button_slots",
            "runtime",
            "cancel",
        ) + (() if self._lightweight else ("connection",))
        return self._form(
            "summary",
            {
                **self._actions(actions, "save"),
                vol.Required("confirm_save", default=False): selector.BooleanSelector(),
            },
            errors,
            **self._texts(summary=self._summary, diff=self._diff),
        )

    async def _commit(self, checked: Any) -> dict:
        data = transport.make_entry_data(self._connection, checked)
        data.pop("scan_interval_s", None)
        if self._entry:
            data = {
                **self._entry.data,
                **data,
                "identity_token": self._entry.data["identity_token"],
            }
            from . import async_commit_configuration

            await async_commit_configuration(
                self.hass, self._entry, data, deepcopy(self._draft)
            )
            return self.async_abort(reason="reconfigure_successful")
        fingerprint = hardware_fingerprint(checked.identity.as_dict())
        await self.async_set_unique_id(fingerprint)
        self._abort_if_unique_id_configured()
        data["identity_token"] = identity_token(fingerprint, fingerprint)
        return self.async_create_entry(
            title=checked.title, data=data, options=deepcopy(self._draft)
        )


class ConfigFlow(V3Wizard, config_entries.ConfigFlow, domain=DOMAIN):
    """Register only the canonical v3 wizard."""

    VERSION = 3

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> Any:
        return FuturaOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict | None = None) -> dict:
        self._initialize()
        await self._load_language()
        for group, kind in (("sensor_slots", "sensor"), ("button_slots", "button")):
            for index, slot in self._draft[group].items():
                slot["name"] = f"{self._t(kind)} {index}"
        for key, zone in self._draft["zones"].items():
            kind, index = key.split("_")
            zone["name"] = f"{self._t(kind)} {index}"
        return await self.async_step_connection(user_input)

    async def async_step_reconfigure(self, user_input: dict | None = None) -> dict:
        if not hasattr(self, "_draft"):
            self._initialize(self._get_reconfigure_entry())
        return await self.async_step_connection(user_input)


class FuturaOptionsFlow(V3Wizard, config_entries.OptionsFlow):
    """Lightweight metadata/runtime editor; source modes use the full flow."""

    def __init__(self, entry: Any) -> None:
        self._initialize(entry, lightweight=True)

    async def async_step_init(self, user_input: dict | None = None) -> dict:
        await self._load_language()
        if user_input:
            if user_input["action"] == "full":
                return await self.async_step_full_configuration()
            return await self._route(user_input["action"])
        return self._form(
            "init",
            self._actions(
                ("runtime", "zones", "sensor_slots", "button_slots", "full", "cancel"),
                "runtime",
            ),
        )

    async def async_step_full_configuration(
        self, user_input: dict | None = None
    ) -> dict:
        if user_input is not None:
            return self.async_abort(reason="reconfigure_required")
        return self.async_show_form(
            step_id="full_configuration",
            data_schema=vol.Schema({}),
            description_placeholders={"entry_id": self._entry.entry_id},
        )


def _connection_error(err: Exception) -> str:
    if isinstance(err, transport.IncompleteIdentityError):
        return "cannot_read_identity"
    if isinstance(err, transport.InvalidProfileError):
        return "invalid_profile"
    if isinstance(err, transport.NotFuturaDeviceError):
        return "not_futura_device"
    return "cannot_connect"
