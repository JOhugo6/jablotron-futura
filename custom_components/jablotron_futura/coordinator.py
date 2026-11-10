"""Modbus coordinator and connection validation for Jablotron Futura."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import inspect
import asyncio
import time
import logging
from typing import Any

from pymodbus.client import AsyncModbusTcpClient

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEVICE_IDENTITY,
    CONF_DEVICE_VARIANT,
    CONF_ETHERNET_MAC,
    CONF_FIRMWARE_REVISION,
    CONF_HOST,
    CONF_HARDWARE_REVISION,
    CONF_PORT,
    CONF_PROFILE_MODE,
    CONF_RESOLVED_PROFILE,
    CONF_SCAN_INTERVAL_S,
    CONF_SERIAL_NUMBER,
    CONF_UNIT_ID,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL_S,
    DEFAULT_UNIT_ID,
    EMERGENCY_WARNING_BIT,
    ENTRY_TITLE_PREFIX,
    FUTURA_DEVICE_ID,
    PROFILE_MODE_AUTO,
    SLOT_COUNT,
)
from .identity import (
    make_connection_unique_id,
    make_device_identifier,
    make_entry_title,
)
from .models import ButtonActivationState, DeviceIdentity, FuturaConfigEntry
from .profiles import RegisterProfile, get_profile
from .models import load_v3_options
from .readback import decode_sensor, decode_button
from .transport import (
    acquire_transport,
    release_transport,
    TransportError,
    EndpointTransport,
)
from homeassistant.helpers.storage import Store
from .validation import derive_discovered_zones

_LOGGER = logging.getLogger(__name__)


class CannotConnectError(Exception):
    """Raised when Modbus TCP connect or read fails."""


class InvalidProfileError(Exception):
    """Raised when profile autodetection is ambiguous or invalid."""


class NotFuturaDeviceError(Exception):
    """Raised when probe data does not look like a Futura controller."""


class IncompleteIdentityError(Exception):
    """Raised when the required identity fields are missing or unusable."""


@dataclass(slots=True, frozen=True)
class ValidationResult:
    """Connection validation result used by config flow."""

    host: str
    port: int
    unit_id: int
    requested_profile_mode: str
    resolved_profile: str
    variant_raw: int
    fut_config_raw: int
    identity: DeviceIdentity
    topology_snapshot: dict[str, Any]

    @property
    def unique_id(self) -> str:
        """Return stable config entry unique id for the current connection tuple."""
        return make_connection_unique_id(self.host, self.port, self.unit_id)

    @property
    def title(self) -> str:
        """Return config entry title."""
        return make_entry_title(self.unit_id)


class FuturaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """DataUpdateCoordinator that polls the controller over Modbus TCP."""

    def __init__(self, hass: HomeAssistant, entry: FuturaConfigEntry) -> None:
        self.entry = entry
        self._identity_snapshot = dict(entry.data.get(CONF_DEVICE_IDENTITY, entry.data))
        self.config = load_v3_options(dict(entry.options))
        self._transport = None
        self._verified_generation = -1
        self.identity_error = None
        self._frozen = False
        self.generation = 0
        self._readback_task = None
        self._readback_wake = asyncio.Event()
        self.sensor_readback = {}
        self.last_sensor_write = {}
        self.button_readback = {}
        self.clear_report = []
        self.button_recovery = {}
        self._store = Store(hass, 1, f"jablotron_futura.{entry.entry_id}.runtime")
        self.scheduler = {
            "requested_interval_ms": self.config["runtime"]["read_interval_ms"],
            "coalesced": 0,
        }
        self.buttons = None
        self.host = str(entry.data[CONF_HOST])
        self.port = int(entry.data.get(CONF_PORT, DEFAULT_PORT))
        self.unit_id = int(entry.data.get(CONF_UNIT_ID, DEFAULT_UNIT_ID))
        self.profile = get_profile(str(entry.data[CONF_RESOLVED_PROFILE]))
        self._client: AsyncModbusTcpClient | None = None
        self._device_kwarg = _get_device_kwarg_name()
        self._has_connected_once = False
        self.button_activation_states: dict[str, ButtonActivationState] = {}
        self.last_button_activation_attempt: dict[str, Any] | None = None
        self.reconnect_generation = 0

        super().__init__(
            hass,
            _LOGGER,
            name=ENTRY_TITLE_PREFIX,
            config_entry=entry,
            update_interval=dt.timedelta(
                seconds=self.config["runtime"]["scan_interval_s"]
            ),
        )

    async def async_record_clear(self, report: dict[str, Any]) -> None:
        report = dict(
            report,
            old_profile=self.profile.profile_id,
            attempted_at=dt_util.utcnow().isoformat(),
        )
        self.clear_report = (self.clear_report + [report])[-16:]
        latest = {(item.get("kind"), item["slot"]): item for item in self.clear_report}
        from homeassistant.helpers import issue_registry as ir

        issue = f"{self.entry.entry_id}_cleanup_failed"
        if report["result"] != "ok":
            ir.async_create_issue(
                self.hass,
                "jablotron_futura",
                issue,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="cleanup_failed",
            )
        elif not self.button_recovery and all(
            item["result"] == "ok" for item in latest.values()
        ):
            ir.async_delete_issue(self.hass, "jablotron_futura", issue)
        from .persistence import async_save_store

        try:
            await async_save_store(
                self._store,
                {
                    "clear_report": self.clear_report,
                    "button_recovery": self.button_recovery,
                },
            )
        except Exception:
            self._frozen = True
            ir.async_create_issue(
                self.hass,
                "jablotron_futura",
                f"{self.entry.entry_id}_runtime_storage_failed",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="runtime_storage_failed",
            )
            raise
        _LOGGER.info(
            "Ownership cleanup slot %s: %s", report.get("slot"), report.get("result")
        )

    async def async_start_runtime(self) -> None:
        from .button_runtime import ButtonRuntime

        saved = await self._store.async_load() or {}
        self.clear_report = saved.get("clear_report", [])[-16:]
        self.button_recovery = saved.get("button_recovery", {})
        self.buttons = ButtonRuntime(self)
        self.buttons.restore()
        await self._async_readback_cycle()
        self._readback_task = asyncio.create_task(self._readback_loop())

    async def async_recover_buttons(self, slots: list[str]) -> None:
        if self.buttons:
            for slot in slots:
                await self.buttons.takeover(int(slot))

    async def async_freeze(self) -> None:
        self._frozen = True
        self.generation += 1
        if self.buttons:
            await self.buttons.freeze()
        if self._readback_task:
            self._readback_task.cancel()
            await asyncio.gather(self._readback_task, return_exceptions=True)
            self._readback_task = None
        if self._transport:
            async with self._transport.lock:
                pass

    async def async_resume(self) -> None:
        self._frozen = False
        if self.buttons:
            await self.buttons.resume()
        if not self._readback_task:
            self._readback_task = asyncio.create_task(self._readback_loop())

    async def async_stop(self, clear: bool = True) -> None:
        await self.async_freeze()
        if clear and not self.config.get("migration_needs_repair") and self.buttons:
            await self.buttons.clear_owned()

    async def async_record_skipped_clear(self) -> None:
        """Record ownership not reached before the entry-wide clear deadline."""
        if self.buttons:
            for key in sorted(self.buttons.owned):
                state = self.buttons.states[key]
                if state["state"] == "cleanup_failed":
                    continue
                state["state"] = "cleanup_failed"
                state["cleanup_result"] = "skipped_timeout"
                self.button_recovery[key] = dict(state)
                await self.async_record_clear(
                    {
                        "kind": "button",
                        "slot": int(key),
                        "generation": self.generation,
                        "result": "skipped_timeout",
                        "error_code": "deadline",
                    }
                )

    async def async_clear_owned(self) -> None:
        await self.async_stop(clear=True)

    async def _readback_loop(self) -> None:
        interval = self.config["runtime"]["read_interval_ms"] / 1000
        due = time.monotonic() + interval
        while not self._frozen:
            await self._async_wait_readback(max(0, due - time.monotonic()))
            self._readback_wake.clear()
            await self._async_readback_cycle()
            now = time.monotonic()
            if now >= due:
                skipped = max(0, int((now - due) // interval))
                self.scheduler["coalesced"] += skipped
                due += (skipped + 1) * interval

    async def _async_wait_readback(self, delay: float) -> None:
        """Wake at the next cadence boundary or a coalesced post-write request."""
        try:
            async with asyncio.timeout(delay):
                await self._readback_wake.wait()
        except TimeoutError:
            pass

    async def _async_readback_cycle(self) -> None:
        started = time.monotonic()
        previous = self.scheduler.get("last_started_monotonic")
        self.scheduler["effective_interval_s"] = (
            started - previous if previous is not None else None
        )
        self.scheduler["last_started_monotonic"] = started
        for kind, states, block, decoder, mode_key in (
            (
                "sensor_slots",
                self.sensor_readback,
                self.profile.external_sensor_block,
                decode_sensor,
                "mode",
            ),
            (
                "button_slots",
                self.button_readback,
                self.profile.external_button_block,
                decode_button,
                "ownership",
            ),
        ):
            for key, config in self.config[kind].items():
                if not config["enabled"] or config[mode_key] == "none":
                    states[key] = {"available": False}
                    continue
                address, count = block(int(key))
                try:
                    decoded = decoder(
                        await self._read_holding_registers(address, count)
                    )
                    if kind == "sensor_slots":
                        expected = self.last_sensor_write.get(key)
                        decoded["mismatch"] = (
                            expected is not None and decoded["raw"] != expected
                        )
                    states[key] = decoded | {
                        "available": True,
                        "timestamp": dt_util.utcnow().isoformat(),
                        "read_monotonic": time.monotonic(),
                    }
                except (UpdateFailed, ValueError):
                    previous_block = states.get(key, {})
                    states[key] = {
                        "available": False,
                        "last_raw": previous_block.get(
                            "raw", previous_block.get("last_raw")
                        ),
                        "last_timestamp": previous_block.get(
                            "timestamp", previous_block.get("last_timestamp")
                        ),
                        "error_code": "read_failed",
                    }
                if (
                    kind == "button_slots"
                    and self.buttons
                    and not self.config.get("migration_needs_repair")
                ):
                    await self.buttons.observe_startup(key, states[key])
        self.scheduler["duration_s"] = time.monotonic() - started
        self.scheduler["delayed"] = (
            self.scheduler["duration_s"]
            > self.config["runtime"]["read_interval_ms"] / 1000
        )
        if self.data is not None:
            self.data["sensor_slots"] = self.sensor_readback
            self.data["button_slots"] = self.button_readback
            self.async_update_listeners()

    def readback_available(self, kind: str, slot: int) -> bool:
        state = (
            self.sensor_readback if kind == "sensor" else self.button_readback
        ).get(str(slot), {})
        return bool(
            state.get("available")
            and time.monotonic() - state.get("read_monotonic", 0)
            <= max(15, 3 * self.config["runtime"]["read_interval_ms"] / 1000)
        )

    async def _get_transport(self) -> EndpointTransport:
        if self._transport is None:
            self._transport = await acquire_transport(
                self.host, self.port, factory=AsyncModbusTcpClient
            )
            self._transport.retry_interval = self.config["runtime"]["scan_interval_s"]
        return self._transport

    async def _drop_client(self) -> None:
        if self._transport:
            await self._transport.close()

    async def async_close(self) -> None:
        await self.async_freeze()
        if self._transport:
            await release_transport(self._transport)
            self._transport = None

    async def _request(self, method: str, address: int, **kwargs: Any) -> Any:
        try:
            transport = await self._get_transport()
            result = await transport.request(self.unit_id, method, address, **kwargs)
            self.reconnect_generation = transport.generation
            return result
        except TransportError as err:
            raise UpdateFailed(str(err)) from err

    async def _read_input_registers(self, address: int, count: int) -> list[int]:
        return await self._request("read_input_registers", address, count=count)

    async def _read_holding_registers(self, address: int, count: int) -> list[int]:
        return await self._request("read_holding_registers", address, count=count)

    def _write_guard(self, generation: int, cleanup: bool = False) -> None:
        if self.config.get("migration_needs_repair") or generation != self.generation:
            raise TransportError("writes_blocked")
        if self._frozen and not cleanup:
            raise TransportError("writes_frozen")
        if self._verified_generation != self._transport.generation:
            raise TransportError("identity_not_verified")

    async def _verify_identity(self) -> None:
        transport = await self._get_transport()
        if (
            self._verified_generation == transport.generation
            and transport.client is not None
            and transport.client.connected
        ):
            return
        try:
            identity, _, _, verified_generation = await _probe_identity(
                transport, self.unit_id, self.profile.profile_id
            )
        except (
            InvalidProfileError,
            NotFuturaDeviceError,
            IncompleteIdentityError,
        ) as err:
            self.identity_error = "identity_or_profile_invalid"
            raise UpdateFailed(self.identity_error) from err
        expected = DeviceIdentity.from_mapping(self._identity_snapshot)
        if (
            identity.serial_number != expected.serial_number
            or identity.ethernet_mac.lower() != expected.ethernet_mac.lower()
        ):
            self._frozen = True
            self.identity_error = "identity_mismatch"
            from homeassistant.helpers import issue_registry as ir

            ir.async_create_issue(
                self.hass,
                "jablotron_futura",
                f"{self.entry.entry_id}_identity_mismatch",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="identity_mismatch",
            )
            raise UpdateFailed("identity_mismatch")
        self._verified_generation = verified_generation
        self.reconnect_generation = transport.generation

    async def _write_holding_register(self, address: int, value: int) -> None:
        generation = self.generation
        await self._verify_identity()
        await self._request(
            "write_register",
            address,
            value=value,
            guard=lambda: self._write_guard(generation),
        )

    async def _write_holding_registers(
        self, address: int, values: list[int], *, cleanup: bool = False
    ) -> None:
        generation = self.generation
        await self._verify_identity()
        await self._request(
            "write_registers",
            address,
            values=values,
            guard=lambda: self._write_guard(generation, cleanup),
        )

    async def async_write_external_sensor_block(
        self, slot_index: int, payload: list[int], *, cleanup: bool = False
    ) -> None:
        """Write one external sensor slot payload."""
        decode_sensor(payload)
        cfg = self.config["sensor_slots"][str(slot_index)]
        if not cleanup and not (
            cfg["enabled"]
            and cfg["mode"] == "ha_writeback"
            and self.config["runtime"]["bridge_enabled"]
        ):
            raise UpdateFailed("slot_not_owned")
        address, _count = self.profile.external_sensor_block(slot_index)
        await self._write_holding_registers(address, payload, cleanup=cleanup)
        self.last_sensor_write[str(slot_index)] = list(payload)
        self._readback_wake.set()

    async def async_write_external_button_block(
        self, slot_index: int, payload: list[int], *, cleanup: bool = False
    ) -> None:
        """Write one external button payload block."""
        decode_button(payload)
        cfg = self.config["button_slots"][str(slot_index)]
        if not cleanup and not (cfg["enabled"] and cfg["ownership"] == "ha_control"):
            raise UpdateFailed("slot_not_owned")
        address, _count = self.profile.external_button_block(slot_index)
        await self._write_holding_registers(address, payload, cleanup=cleanup)
        self._readback_wake.set()

    async def async_set_vent_mode(self, value: int) -> None:
        """Write the base ventilation mode."""
        await self.async_write_standard_holding_key("mode_raw", value)

    async def async_set_humidity_target_raw(self, value: int) -> None:
        """Write humidity target register."""
        await self.async_write_standard_holding_key("humi_set_raw", value)

    async def async_write_standard_holding_key(self, key: str, value: int) -> None:
        """Write a standard holding register by profile key."""
        address = self.profile.holding_address(key)
        limits = {
            0: (0, 6),
            1: (0, 7200),
            2: (0, 21600),
            4: (0, 28800),
            5: (0, 28800),
            10: (150, 280),
            11: (250, 750),
            12: (0, 1),
            14: (0, 1),
            15: (0, 1),
            16: (0, 1),
            17: (0, 1),
        }
        if (
            type(value) is not int
            or address not in limits
            or not limits[address][0] <= value <= limits[address][1]
        ):
            raise ValueError("invalid_standard_write")
        if (
            address == 10
            and value % 5
            or address == 11
            and value not in (250, 500, 750)
        ):
            raise ValueError("invalid_standard_step")
        await self._write_holding_register(address, value)
        await self.async_request_refresh()

    async def async_set_number_key(self, key: str, value: int) -> None:
        """Write a numeric standard holding register."""
        await self.async_write_standard_holding_key(key, value)

    async def async_set_switch_key(self, key: str, enabled: bool) -> None:
        """Write a boolean switch register."""
        await self.async_write_standard_holding_key(key, 1 if enabled else 0)

    def external_button_diagnostics_snapshot(self) -> dict[str, Any]:
        """Return runtime diagnostics for configured external-button activations."""
        return {
            "slots": self.config["button_slots"],
            "states": self.buttons.states if self.buttons else {},
            "recovery": self.button_recovery,
            "readback": self.button_readback,
        }

    def _maybe_persist_identity(self, identity: DeviceIdentity) -> None:
        """Persist device identity changes back to the config entry data."""
        if not identity.is_complete():
            return
        current_identity = DeviceIdentity.from_mapping(self.entry.data)
        if current_identity == identity:
            return
        if not hasattr(self.hass, "config_entries"):
            return

        updated_data = dict(self.entry.data)
        updated_data.update(identity.as_dict())
        updated_data[CONF_DEVICE_IDENTITY] = identity.as_dict()
        self.hass.config_entries.async_update_entry(self.entry, data=updated_data)
        self._update_device_identity_metadata(identity)

    def _update_device_identity_metadata(self, identity: DeviceIdentity) -> None:
        """Push live identity changes into the Home Assistant device registry."""
        device_registry = dr.async_get(self.hass)
        device_entry = device_registry.async_get_device(
            identifiers={
                make_device_identifier(self.entry.unique_id, self.entry.entry_id)
            }
        )
        if device_entry is None:
            return

        device_registry.async_update_device(
            device_entry.id,
            model=identity.device_variant or self.profile.profile_label,
            hw_version=identity.hardware_revision or None,
            sw_version=identity.firmware_revision or None,
            serial_number=identity.serial_number or None,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll standard input and holding register state."""
        try:
            await self._verify_identity()
            data = await self._async_read_standard_data()
        except Exception as err:  # noqa: BLE001
            await self._drop_client()
            raise UpdateFailed("poll_failed") from err

        data["resolved_profile"] = self.profile.profile_id
        data["profile_label"] = self.profile.profile_label
        data["emergency_shutdown_active"] = bool(
            (int(data["warnings_bits_raw"]) >> EMERGENCY_WARNING_BIT) & 1
        )
        data["last_poll_at"] = dt_util.utcnow().isoformat()
        data["sensor_slots"] = self.sensor_readback
        data["button_slots"] = self.button_readback
        return data

    async def _async_read_standard_data(self) -> dict[str, Any]:
        """Read and parse the baseline standard registers."""
        input_blocks = {
            address: await self._read_input_registers(address, count)
            for address, count in self.profile.input_segments
        }
        input_blocks[0] = await self._read_input_registers(0, 10)
        input_blocks[70] = await self._read_input_registers(70, 6)
        input_blocks[80] = await self._read_input_registers(80, 1)
        alfa_connected_address = self.profile.input_address("alfa_connected_bits")
        inp_alfa_bits = await self._read_input_registers(alfa_connected_address, 1)
        hold_main = await self._read_holding_registers(*self.profile.holding_segment)

        data: dict[str, Any] = {}
        data["fact_device_id"] = _read_input_u16(
            input_blocks, self.profile, "fact_device_id"
        )
        data["variant_raw"] = _read_input_u16(input_blocks, self.profile, "variant_raw")
        data["fut_config_raw"] = _read_input_u16(
            input_blocks, self.profile, "fut_config_raw"
        )
        data["modes_bits_raw"] = _read_input_u32(
            input_blocks, self.profile, "modes_bits_raw"
        )
        data["errors_bits_raw"] = _read_input_u32(
            input_blocks, self.profile, "errors_bits_raw"
        )
        data["warnings_bits_raw"] = _read_input_u32(
            input_blocks, self.profile, "warnings_bits_raw"
        )
        identity = _build_device_identity_from_input_blocks(
            input_blocks,
            self.profile,
            data["variant_raw"],
        )
        data[CONF_DEVICE_IDENTITY] = identity.as_dict()
        data[CONF_DEVICE_VARIANT] = identity.device_variant
        data[CONF_SERIAL_NUMBER] = identity.serial_number
        data[CONF_ETHERNET_MAC] = identity.ethernet_mac
        data[CONF_HARDWARE_REVISION] = identity.hardware_revision
        data[CONF_FIRMWARE_REVISION] = identity.firmware_revision

        fut_config_raw = data["fut_config_raw"]
        data["has_internal_heater"] = bool(fut_config_raw & 0x1)
        data["has_coolbreeze_cooling"] = bool(fut_config_raw & 0x2)
        data["has_coolbreeze_heating"] = bool(fut_config_raw & 0x4)
        data["has_bypass"] = bool(fut_config_raw & 0x8)
        data["heating_available"] = bool(
            data["has_internal_heater"] or data["has_coolbreeze_heating"]
        )
        data["cooling_available"] = bool(data["has_coolbreeze_cooling"])
        data["bypass_available"] = bool(data["has_bypass"])

        data["temp_outdoor"] = (
            _read_input_i16(input_blocks, self.profile, "temp_outdoor") / 10.0
        )
        data["temp_supply"] = (
            _read_input_i16(input_blocks, self.profile, "temp_supply") / 10.0
        )
        data["temp_extract"] = (
            _read_input_i16(input_blocks, self.profile, "temp_extract") / 10.0
        )
        data["temp_exhaust"] = (
            _read_input_i16(input_blocks, self.profile, "temp_exhaust") / 10.0
        )
        data["temp_outdoor_ntc"] = (
            _read_input_i16(input_blocks, self.profile, "temp_outdoor_ntc") / 10.0
        )

        data["humi_outdoor"] = (
            _read_input_u16(input_blocks, self.profile, "humi_outdoor") / 10.0
        )
        data["humi_supply"] = (
            _read_input_u16(input_blocks, self.profile, "humi_supply") / 10.0
        )
        data["humi_extract"] = (
            _read_input_u16(input_blocks, self.profile, "humi_extract") / 10.0
        )
        data["humi_exhaust"] = (
            _read_input_u16(input_blocks, self.profile, "humi_exhaust") / 10.0
        )

        data["filter_wear"] = _read_input_u16(input_blocks, self.profile, "filter_wear")
        data["power"] = _read_input_u16(input_blocks, self.profile, "power")
        data["heat_recovering"] = _read_input_u16(
            input_blocks, self.profile, "heat_recovering"
        )
        data["heating_power"] = _read_input_u16(
            input_blocks, self.profile, "heating_power"
        )
        data["air_flow"] = _read_input_u16(input_blocks, self.profile, "air_flow")
        data["fan_power_supply_raw"] = _read_input_u16(
            input_blocks, self.profile, "fan_power_supply_raw"
        )
        data["fan_power_exhaust_raw"] = _read_input_u16(
            input_blocks, self.profile, "fan_power_exhaust_raw"
        )
        data["fan_rpm_supply"] = _read_input_u16(
            input_blocks, self.profile, "fan_rpm_supply"
        )
        data["fan_rpm_exhaust"] = _read_input_u16(
            input_blocks, self.profile, "fan_rpm_exhaust"
        )
        data["rtc_batt_voltage"] = _read_input_u16(
            input_blocks, self.profile, "rtc_batt_voltage"
        )
        data["connected_supply_valves_bits"] = _read_input_valves_u32(
            input_blocks, self.profile, "connected_supply_valves_bits"
        )
        data["connected_exhaust_valves_bits"] = _read_input_valves_u32(
            input_blocks, self.profile, "connected_exhaust_valves_bits"
        )
        data["connected_buttons_bits"] = _read_input_u16(
            input_blocks, self.profile, "connected_button_bits"
        )
        data["vzv_identify_bits"] = _read_input_u16(
            input_blocks, self.profile, "vzv_identify_bits"
        )

        alfa_bits = _u16_from(
            inp_alfa_bits,
            alfa_connected_address,
            alfa_connected_address,
        )
        data["alfa_connected_bits"] = alfa_bits
        data["alfa_count"] = alfa_bits.bit_count()
        for slot_index in range(1, 9):
            connected = bool(alfa_bits & (1 << (slot_index - 1)))
            data[f"alfa_{slot_index}_available"] = connected
            if not connected:
                continue
            base, count = self.profile.alfa_block(slot_index)
            alfa_block = await self._read_input_registers(base, count)
            data[f"alfa_mb_address_{slot_index}"] = _u16_from(alfa_block, base, base)
            data[f"alfa_options_{slot_index}"] = _u16_from(alfa_block, base, base + 1)
            data[f"alfa_co2_{slot_index}"] = _u16_from(alfa_block, base, base + 2)
            data[f"alfa_temp_{slot_index}"] = (
                _i16_from(alfa_block, base, base + 3) / 10.0
            )
            data[f"alfa_humi_{slot_index}"] = (
                _u16_from(alfa_block, base, base + 4) / 10.0
            )
            data[f"alfa_ntc_temp_{slot_index}"] = (
                _i16_from(alfa_block, base, base + 5) / 10.0
            )

        zone_runtime_values = {}

        for key in (
            "mode_raw",
            "boost_remaining_s",
            "circulation_remaining_s",
            "overpressure_remaining_s",
            "night_remaining_s",
            "party_remaining_s",
            "time_program_raw",
            "antiradon_raw",
            "bypass_enable_raw",
            "heating_enable_raw",
            "cooling_enable_raw",
            "comfort_enable_raw",
        ):
            data[key] = _u16_from(
                hold_main,
                self.profile.holding_segment[0],
                self.profile.holding_address(key),
            )

        data["away_begin_ts"] = _u32_from(
            hold_main,
            self.profile.holding_segment[0],
            self.profile.holding_address("away_begin_ts"),
        )
        data["away_end_ts"] = _u32_from(
            hold_main,
            self.profile.holding_segment[0],
            self.profile.holding_address("away_end_ts"),
        )
        data["temp_set_raw"] = (
            _u16_from(
                hold_main,
                self.profile.holding_segment[0],
                self.profile.holding_address("temp_set_raw"),
            )
            / 10.0
        )
        data["humi_set_raw"] = (
            _u16_from(
                hold_main,
                self.profile.holding_segment[0],
                self.profile.holding_address("humi_set_raw"),
            )
            / 10.0
        )
        data["mode_text"] = VENT_MODE_INV.get(int(data["mode_raw"]), "Unknown")

        for key in ("boost_remaining_s", "circulation_remaining_s"):
            raw_seconds = int(data[key] or 0)
            data[key.replace("_s", "_min")] = (raw_seconds + 59) // 60

        for key in ("night_remaining_s", "party_remaining_s"):
            raw_seconds = int(data[key] or 0)
            data[key.replace("_s", "_h")] = (
                0 if raw_seconds == 0 else (raw_seconds + 3599) // 3600
            )

        for key in ("away_begin_ts", "away_end_ts"):
            timestamp = int(data[key] or 0)
            data[key.replace("_ts", "_text")] = (
                "Not set"
                if timestamp == 0
                else dt_util.as_local(dt_util.utc_from_timestamp(timestamp)).strftime(
                    "%Y-%m-%d %H:%M"
                )
            )

        data["topology_snapshot"] = _build_topology_snapshot(
            supply_bits=data["connected_supply_valves_bits"],
            exhaust_bits=data["connected_exhaust_valves_bits"],
            button_bits=data["connected_buttons_bits"],
            alfa_bits=alfa_bits,
            vzv_identify_bits=data["vzv_identify_bits"],
            data=data,
            zone_runtime_values=zone_runtime_values,
        )
        return data


async def _probe_identity(
    transport: EndpointTransport, unit_id: int, profile_mode: str
) -> tuple[DeviceIdentity, int, int, int]:
    if profile_mode not in ("auto", "futura_lms", "lms"):
        raise InvalidProfileError("unsupported_profile")
    try:
        words = await transport.request(unit_id, "read_input_registers", 0, count=10)
        verified_generation = transport.generation
        variant = await transport.request(
            unit_id,
            "read_input_registers",
            14,
            count=2,
            expected_generation=verified_generation,
        )
        if words[0] != FUTURA_DEVICE_ID:
            raise NotFuturaDeviceError
        if variant[0] not in (0, 1, 2):
            raise InvalidProfileError
        if (
            not any(words[1:3])
            or all(word == 65535 for word in words[1:3])
            or not any(words[3:6])
            or all(word == 65535 for word in words[3:6])
            or not any(words[6:8])
            or not any(words[8:10])
        ):
            raise IncompleteIdentityError
        probe = await transport.request(
            unit_id,
            "read_holding_registers",
            300,
            count=6,
            expected_generation=verified_generation,
        )
        decode_sensor(probe)
        identity = _build_device_identity_from_input_blocks(
            {0: words, 14: variant}, get_profile("futura_lms"), variant[0]
        )
        return identity, variant[0], variant[1], verified_generation
    except TransportError as err:
        raise CannotConnectError from err
    except ValueError as err:
        raise InvalidProfileError from err


async def async_validate_connection(
    host: str, port: int, unit_id: int, profile_mode: str
) -> ValidationResult:
    """Read-only LMS gate sharing the live endpoint session with flows."""
    if profile_mode not in ("auto", "futura_lms", "lms"):
        raise InvalidProfileError("unsupported_profile")
    transport = None
    try:
        transport = await acquire_transport(host, port, factory=AsyncModbusTcpClient)
        identity, variant, config, _ = await _probe_identity(
            transport, unit_id, profile_mode
        )
        topology = await _async_read_topology_snapshot(
            transport, unit_id, get_profile("futura_lms")
        )
        return ValidationResult(
            host,
            port,
            unit_id,
            profile_mode,
            "futura_lms",
            variant,
            config,
            identity,
            topology,
        )
    except TransportError as err:
        raise CannotConnectError from err
    finally:
        if transport is not None:
            await release_transport(transport)


async def async_preview_slots(
    host: str,
    port: int,
    unit_id: int,
    profile_mode: str,
    sensor_slots: list[int],
    button_slots: list[int],
) -> dict[str, Any]:
    if profile_mode not in ("auto", "futura_lms", "lms"):
        raise InvalidProfileError("unsupported_profile")
    transport = None
    try:
        transport = await acquire_transport(host, port, factory=AsyncModbusTcpClient)
        await _probe_identity(transport, unit_id, profile_mode)
        profile = get_profile("futura_lms")
        result = {"sensor_slots": {}, "button_slots": {}}
        for kind, indexes, block, decoder in (
            (
                "sensor_slots",
                sensor_slots,
                profile.external_sensor_block,
                decode_sensor,
            ),
            (
                "button_slots",
                button_slots,
                profile.external_button_block,
                decode_button,
            ),
        ):
            for slot in indexes:
                address, count = block(slot)
                try:
                    result[kind][str(slot)] = decoder(
                        await transport.request(
                            unit_id, "read_holding_registers", address, count=count
                        )
                    ) | {"available": True}
                except (TransportError, ValueError):
                    result[kind][str(slot)] = {
                        "available": False,
                        "error_code": "read_failed",
                    }
        return result
    except TransportError as err:
        raise CannotConnectError from err
    finally:
        if transport is not None:
            await release_transport(transport)


async def _async_read_topology_snapshot(
    transport: EndpointTransport, unit_id: int, profile: RegisterProfile
) -> dict[str, Any]:
    discovery = await transport.request(unit_id, "read_input_registers", 70, count=6)
    identify = await transport.request(unit_id, "read_input_registers", 80, count=1)
    data = {}
    for slot in range(1, 9):
        if discovery[5] & (1 << (slot - 1)):
            base, count = profile.alfa_block(slot)
            words = await transport.request(
                unit_id, "read_input_registers", base, count=count
            )
            for key, value in _parse_alfa_live_block(words, base).items():
                mapped = {
                    "mb_address": "mb_address",
                    "options": "options",
                    "co2": "co2",
                    "temperature": "temp",
                    "humidity": "humi",
                    "ntc_temperature": "ntc_temp",
                }[key]
                data[f"alfa_{mapped}_{slot}"] = value
    return _build_topology_snapshot(
        _connected_valves_u32_from(discovery, 70, 70),
        _connected_valves_u32_from(discovery, 70, 72),
        discovery[4],
        discovery[5],
        identify[0],
        data,
        {},
    )


def make_entry_data(
    user_input: dict[str, Any], validation: ValidationResult
) -> dict[str, Any]:
    """Build config entry data from flow input and validation result."""
    return {
        CONF_HOST: validation.host,
        CONF_PORT: validation.port,
        CONF_UNIT_ID: validation.unit_id,
        CONF_PROFILE_MODE: str(user_input.get(CONF_PROFILE_MODE, PROFILE_MODE_AUTO)),
        CONF_RESOLVED_PROFILE: validation.resolved_profile,
        CONF_SCAN_INTERVAL_S: int(
            user_input.get(CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S)
        ),
        CONF_DEVICE_IDENTITY: validation.identity.as_dict(),
        **validation.identity.as_dict(),
    }


def _get_device_kwarg_name() -> str:
    signature = inspect.signature(AsyncModbusTcpClient.read_input_registers)
    return "device_id" if "device_id" in signature.parameters else "slave"


def _to_signed_16bit(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def _u32_from(block: list[int], base: int, address: int) -> int:
    index = address - base
    return (block[index] << 16) | block[index + 1]


def _connected_valves_u32_from(block: list[int], base: int, address: int) -> int:
    """Valve discovery pairs 70/71 and 72/73 carry the low word first."""
    index = address - base
    return block[index] | (block[index + 1] << 16)


def _u16_from(block: list[int], base: int, address: int) -> int:
    return int(block[address - base])


def _i16_from(block: list[int], base: int, address: int) -> int:
    return _to_signed_16bit(_u16_from(block, base, address))


def _find_block_for_address(
    blocks: dict[int, list[int]], address: int
) -> tuple[int, list[int]]:
    for base, block in blocks.items():
        if base <= address < base + len(block):
            return base, block
    raise KeyError(f"No input block loaded for address {address}")


def _read_input_u16(
    blocks: dict[int, list[int]], profile: RegisterProfile, key: str
) -> int:
    address = profile.input_address(key)
    base, block = _find_block_for_address(blocks, address)
    return _u16_from(block, base, address)


def _read_input_u32(
    blocks: dict[int, list[int]], profile: RegisterProfile, key: str
) -> int:
    address = profile.input_address(key)
    base, block = _find_block_for_address(blocks, address)
    return _u32_from(block, base, address)


def _read_input_valves_u32(
    blocks: dict[int, list[int]], profile: RegisterProfile, key: str
) -> int:
    address = profile.input_address(key)
    base, block = _find_block_for_address(blocks, address)
    return _connected_valves_u32_from(block, base, address)


def _read_input_i16(
    blocks: dict[int, list[int]], profile: RegisterProfile, key: str
) -> int:
    address = profile.input_address(key)
    base, block = _find_block_for_address(blocks, address)
    return _i16_from(block, base, address)


def _build_device_identity_from_input_blocks(
    input_blocks: dict[int, list[int]],
    profile: RegisterProfile,
    variant_raw: int,
) -> DeviceIdentity:
    """Parse the device identity from input registers."""
    serial_raw = _read_input_u32(input_blocks, profile, "fact_serial_number")
    mac_base = profile.input_address("fact_ethernet_mac")
    mac_block_base, mac_block = _find_block_for_address(input_blocks, mac_base)
    mac_words = [
        _u16_from(mac_block, mac_block_base, mac_base + offset) for offset in range(3)
    ]
    hardware_raw = _read_input_u32(input_blocks, profile, "fact_hw_revision")
    firmware_raw = _read_input_u32(input_blocks, profile, "firm_revision")
    return DeviceIdentity(
        device_variant=_describe_device_variant(variant_raw, profile.profile_id),
        serial_number=str(serial_raw),
        ethernet_mac=_format_mac(mac_words),
        hardware_revision=_format_revision(hardware_raw),
        firmware_revision=_format_revision(firmware_raw),
    )


def _build_topology_snapshot(
    supply_bits: int,
    exhaust_bits: int,
    button_bits: int,
    alfa_bits: int,
    vzv_identify_bits: int,
    data: dict[str, Any],
    zone_runtime_values: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Build the diagnostics/setup topology snapshot payload."""
    discovered_zones = derive_discovered_zones(
        supply_bits=supply_bits,
        exhaust_bits=exhaust_bits,
        button_bits=button_bits,
        alfa_bits=alfa_bits,
        vzv_identify_bits=vzv_identify_bits,
    )
    zones_by_index = {zone.zone_index: zone for zone in discovered_zones}
    zone_payloads = []
    for zone_index in range(1, SLOT_COUNT + 1):
        external_sensor_present = bool(data.get(f"ext_sens_present_{zone_index}", 0))
        external_button_present = bool(data.get(f"ext_btn_present_{zone_index}", 0))
        zone = zones_by_index.get(zone_index)
        if zone is None and not (external_sensor_present or external_button_present):
            continue

        zone_payloads.append(
            {
                "zone_index": zone_index,
                "supply_damper_ids": list(zone.supply_damper_ids)
                if zone is not None
                else [],
                "exhaust_damper_ids": list(zone.exhaust_damper_ids)
                if zone is not None
                else [],
                "button_ids": list(zone.button_ids) if zone is not None else [],
                "alfa_index": zone.alfa_index if zone is not None else None,
                "supply_identify": (
                    zone.supply_identify
                    if zone is not None
                    else bool(vzv_identify_bits & (1 << (zone_index - 1)))
                ),
                "exhaust_identify": (
                    zone.exhaust_identify
                    if zone is not None
                    else bool(vzv_identify_bits & (1 << (SLOT_COUNT + zone_index - 1)))
                ),
                "external_sensor_present": external_sensor_present,
                "external_button_present": external_button_present,
                "alfa_live_values": _zone_alfa_live_values(data, zone_index),
                "external_sensor_live_values": zone_runtime_values.get(zone_index, {}),
            }
        )
    return {
        "connected_supply_valves_bits": supply_bits,
        "connected_exhaust_valves_bits": exhaust_bits,
        "connected_buttons_bits": button_bits,
        "connected_alfa_bits": alfa_bits,
        "vzv_identify_bits": vzv_identify_bits,
        "zones": zone_payloads,
    }


def _zone_alfa_live_values(data: dict[str, Any], zone_index: int) -> dict[str, Any]:
    if f"alfa_mb_address_{zone_index}" not in data:
        return {}
    return {
        "mb_address": data.get(f"alfa_mb_address_{zone_index}"),
        "options": data.get(f"alfa_options_{zone_index}"),
        "co2": data.get(f"alfa_co2_{zone_index}"),
        "temperature": data.get(f"alfa_temp_{zone_index}"),
        "humidity": data.get(f"alfa_humi_{zone_index}"),
        "ntc_temperature": data.get(f"alfa_ntc_temp_{zone_index}"),
    }


def _parse_alfa_live_block(alfa_block: list[int], base: int) -> dict[str, Any]:
    return {
        "mb_address": _u16_from(alfa_block, base, base),
        "options": _u16_from(alfa_block, base, base + 1),
        "co2": _u16_from(alfa_block, base, base + 2),
        "temperature": _i16_from(alfa_block, base, base + 3) / 10.0,
        "humidity": _u16_from(alfa_block, base, base + 4) / 10.0,
        "ntc_temperature": _i16_from(alfa_block, base, base + 5) / 10.0,
    }


def _describe_device_variant(variant_raw: int, resolved_profile: str) -> str:
    if resolved_profile == "futura_lp":
        return "Futura L+"
    return {
        0: "Futura L",
        1: "Futura L",
        2: "Futura M",
    }.get(variant_raw, f"Futura variant {variant_raw}")


def _format_revision(value: int) -> str:
    """Expose vendor raw revision without inventing a semantic version encoding."""
    return f"0x{value:08X}"


def _format_mac(words: list[int]) -> str:
    octets: list[str] = []
    for word in words:
        octets.append(f"{(word >> 8) & 0xFF:02X}")
        octets.append(f"{word & 0xFF:02X}")
    return ":".join(octets)


VENT_MODE_MAP: dict[str, int] = {
    "Off": 0,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "Auto": 6,
}
VENT_MODE_INV = {value: key for key, value in VENT_MODE_MAP.items()}
HUMI_MODE_MAP: dict[str, float] = {
    "Dry": 25.0,
    "Comfort": 50.0,
    "Humid": 75.0,
}
