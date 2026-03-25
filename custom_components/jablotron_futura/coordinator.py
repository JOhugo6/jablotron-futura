"""Modbus coordinator and connection validation for Jablotron Futura."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import inspect
import logging
from typing import Any

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_PROFILE_MODE,
    CONF_RESOLVED_PROFILE,
    CONF_SCAN_INTERVAL_S,
    CONF_UNIT_ID,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL_S,
    DEFAULT_UNIT_ID,
    EMERGENCY_WARNING_BIT,
    ENTRY_TITLE_PREFIX,
    PROFILE_MODE_AUTO,
    SUPPORTED_PROFILES,
)
from .identity import make_connection_unique_id, make_entry_title
from .models import FuturaConfigEntry
from .profiles import RegisterProfile, get_profile

_LOGGER = logging.getLogger(__name__)


class CannotConnectError(Exception):
    """Raised when Modbus TCP connect or read fails."""


class InvalidProfileError(Exception):
    """Raised when profile autodetection is ambiguous or invalid."""


class NotFuturaDeviceError(Exception):
    """Raised when probe data does not look like a Futura controller."""


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
        self.host = str(entry.data[CONF_HOST])
        self.port = int(entry.data.get(CONF_PORT, DEFAULT_PORT))
        self.unit_id = int(entry.data.get(CONF_UNIT_ID, DEFAULT_UNIT_ID))
        self.profile = get_profile(str(entry.data[CONF_RESOLVED_PROFILE]))
        self._client: AsyncModbusTcpClient | None = None
        self._device_kwarg = _get_device_kwarg_name()
        self._has_connected_once = False
        self.reconnect_generation = 0

        super().__init__(
            hass,
            _LOGGER,
            name=ENTRY_TITLE_PREFIX,
            update_interval=dt.timedelta(
                seconds=int(entry.data.get(CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S))
            ),
        )

    async def _ensure_client(self) -> AsyncModbusTcpClient:
        """Ensure an active Modbus TCP connection exists."""
        if self._client is None:
            self._client = AsyncModbusTcpClient(
                self.host,
                port=self.port,
                timeout=5,
                trace_connect=self._handle_transport_state_change,
            )

        if not getattr(self._client, "connected", False):
            try:
                await self._client.connect()
            except Exception as err:  # noqa: BLE001
                await self._drop_client()
                raise UpdateFailed(
                    "Unable to connect to controller"
                ) from err

        if not getattr(self._client, "connected", False):
            await self._drop_client()
            raise UpdateFailed("Unable to connect to controller")

        return self._client

    def _handle_transport_state_change(self, connected: bool) -> None:
        """Track transport reconnects even when pymodbus recovers internally."""
        if not connected:
            return
        if self._has_connected_once:
            self.reconnect_generation += 1
            return
        self._has_connected_once = True

    async def _drop_client(self) -> None:
        """Close the current client and forget it."""
        if self._client is None:
            return
        try:
            await self._client.close()
        except Exception:  # noqa: BLE001
            pass
        self._client = None

    async def async_close(self) -> None:
        """Close resources on unload."""
        await self._drop_client()

    async def _read_input_registers(self, address: int, count: int) -> list[int]:
        """Read input registers and raise UpdateFailed on transport issues."""
        client = await self._ensure_client()
        try:
            response = await client.read_input_registers(
                address, count=count, **{self._device_kwarg: self.unit_id}
            )
        except ModbusException as err:
            await self._drop_client()
            raise UpdateFailed(f"Input register read failed at {address}/{count}") from err
        if response.isError():
            raise UpdateFailed(f"Input register read failed at {address}/{count}: {response}")
        return list(response.registers)

    async def _read_holding_registers(self, address: int, count: int) -> list[int]:
        """Read holding registers and raise UpdateFailed on transport issues."""
        client = await self._ensure_client()
        try:
            response = await client.read_holding_registers(
                address, count=count, **{self._device_kwarg: self.unit_id}
            )
        except ModbusException as err:
            await self._drop_client()
            raise UpdateFailed(
                f"Holding register read failed at {address}/{count}"
            ) from err
        if response.isError():
            raise UpdateFailed(
                f"Holding register read failed at {address}/{count}: {response}"
            )
        return list(response.registers)

    async def _write_holding_register(self, address: int, value: int) -> None:
        """Write a single holding register."""
        client = await self._ensure_client()
        try:
            response = await client.write_register(
                address,
                value=value,
                **{self._device_kwarg: self.unit_id},
            )
        except ModbusException as err:
            await self._drop_client()
            raise UpdateFailed(f"Write failed at {address}") from err
        if response.isError():
            raise UpdateFailed(f"Write failed at {address}: {response}")

    async def _write_holding_registers(self, address: int, values: list[int]) -> None:
        """Write a contiguous block of holding registers."""
        client = await self._ensure_client()
        try:
            response = await client.write_registers(
                address,
                values=values,
                **{self._device_kwarg: self.unit_id},
            )
        except ModbusException as err:
            await self._drop_client()
            raise UpdateFailed(f"Block write failed at {address}") from err
        if response.isError():
            raise UpdateFailed(f"Block write failed at {address}: {response}")

    async def async_write_external_sensor_block(
        self, slot_index: int, payload: list[int]
    ) -> None:
        """Write one external sensor slot payload."""
        address, _count = self.profile.external_sensor_block(slot_index)
        await self._write_holding_registers(address, payload)

    async def async_set_vent_mode(self, value: int) -> None:
        """Write the base ventilation mode."""
        await self.async_write_standard_holding_key("mode_raw", value)
        await self.async_request_refresh()

    async def async_set_humidity_target_raw(self, value: int) -> None:
        """Write humidity target register."""
        await self.async_write_standard_holding_key("humi_set_raw", value)
        await self.async_request_refresh()

    async def async_write_standard_holding_key(self, key: str, value: int) -> None:
        """Write a standard holding register by profile key."""
        await self._write_holding_register(self.profile.holding_address(key), value)
        await self.async_request_refresh()

    async def async_set_number_key(self, key: str, value: int) -> None:
        """Write a numeric standard holding register."""
        await self.async_write_standard_holding_key(key, value)

    async def async_set_switch_key(self, key: str, enabled: bool) -> None:
        """Write a boolean switch register."""
        await self.async_write_standard_holding_key(key, 1 if enabled else 0)
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll standard input and holding register state."""
        try:
            data = await self._async_read_standard_data()
        except Exception as err:  # noqa: BLE001
            await self._drop_client()
            raise UpdateFailed(f"Unexpected Futura polling failure: {err}") from err

        data["resolved_profile"] = self.profile.profile_id
        data["profile_label"] = self.profile.profile_label
        data["emergency_shutdown_active"] = bool(
            (int(data["warnings_bits_raw"]) >> EMERGENCY_WARNING_BIT) & 1
        )
        data["last_poll_at"] = dt_util.utcnow().isoformat()
        return data

    async def _async_read_standard_data(self) -> dict[str, Any]:
        """Read and parse the baseline standard registers."""
        input_blocks = {
            address: await self._read_input_registers(address, count)
            for address, count in self.profile.input_segments
        }
        alfa_connected_address = self.profile.input_address("alfa_connected_bits")
        inp_alfa_bits = await self._read_input_registers(alfa_connected_address, 1)
        hold_main = await self._read_holding_registers(*self.profile.holding_segment)

        data: dict[str, Any] = {}
        data["variant_raw"] = _read_input_u16(input_blocks, self.profile, "variant_raw")
        data["fut_config_raw"] = _read_input_u16(input_blocks, self.profile, "fut_config_raw")
        data["modes_bits_raw"] = _read_input_u32(input_blocks, self.profile, "modes_bits_raw")
        data["errors_bits_raw"] = _read_input_u32(input_blocks, self.profile, "errors_bits_raw")
        data["warnings_bits_raw"] = _read_input_u32(
            input_blocks, self.profile, "warnings_bits_raw"
        )

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

        data["temp_outdoor"] = _read_input_i16(input_blocks, self.profile, "temp_outdoor") / 10.0
        data["temp_supply"] = _read_input_i16(input_blocks, self.profile, "temp_supply") / 10.0
        data["temp_extract"] = _read_input_i16(input_blocks, self.profile, "temp_extract") / 10.0
        data["temp_exhaust"] = _read_input_i16(input_blocks, self.profile, "temp_exhaust") / 10.0
        data["temp_outdoor_ntc"] = _read_input_i16(
            input_blocks, self.profile, "temp_outdoor_ntc"
        ) / 10.0

        data["humi_outdoor"] = _read_input_u16(input_blocks, self.profile, "humi_outdoor") / 10.0
        data["humi_supply"] = _read_input_u16(input_blocks, self.profile, "humi_supply") / 10.0
        data["humi_extract"] = _read_input_u16(input_blocks, self.profile, "humi_extract") / 10.0
        data["humi_exhaust"] = _read_input_u16(input_blocks, self.profile, "humi_exhaust") / 10.0

        data["filter_wear"] = _read_input_u16(input_blocks, self.profile, "filter_wear")
        data["power"] = _read_input_u16(input_blocks, self.profile, "power")
        data["heat_recovering"] = _read_input_u16(input_blocks, self.profile, "heat_recovering")
        data["heating_power"] = _read_input_u16(input_blocks, self.profile, "heating_power")
        data["air_flow"] = _read_input_u16(input_blocks, self.profile, "air_flow")
        data["fan_power_supply_raw"] = _read_input_u16(
            input_blocks, self.profile, "fan_power_supply_raw"
        )
        data["fan_power_exhaust_raw"] = _read_input_u16(
            input_blocks, self.profile, "fan_power_exhaust_raw"
        )
        data["fan_rpm_supply"] = _read_input_u16(input_blocks, self.profile, "fan_rpm_supply")
        data["fan_rpm_exhaust"] = _read_input_u16(input_blocks, self.profile, "fan_rpm_exhaust")
        data["rtc_batt_voltage"] = _read_input_u16(input_blocks, self.profile, "rtc_batt_voltage")

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
            data[f"alfa_temp_{slot_index}"] = _i16_from(alfa_block, base, base + 3) / 10.0
            data[f"alfa_humi_{slot_index}"] = _u16_from(alfa_block, base, base + 4) / 10.0
            data[f"alfa_ntc_temp_{slot_index}"] = (
                _i16_from(alfa_block, base, base + 5) / 10.0
            )

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
        data["temp_set_raw"] = _u16_from(
            hold_main,
            self.profile.holding_segment[0],
            self.profile.holding_address("temp_set_raw"),
        ) / 10.0
        data["humi_set_raw"] = _u16_from(
            hold_main,
            self.profile.holding_segment[0],
            self.profile.holding_address("humi_set_raw"),
        ) / 10.0
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

        return data


async def async_validate_connection(
    host: str,
    port: int,
    unit_id: int,
    profile_mode: str,
) -> ValidationResult:
    """Validate connection details and resolve the final register profile."""
    client = AsyncModbusTcpClient(host, port=port, timeout=5)
    device_kwarg = _get_device_kwarg_name()
    try:
        try:
            await client.connect()
        except Exception as err:  # noqa: BLE001
            raise CannotConnectError from err

        if not getattr(client, "connected", False):
            raise CannotConnectError

        identity_block = await _async_read_input_registers(client, device_kwarg, unit_id, 14, 2)
        variant_raw = int(identity_block[0])
        fut_config_raw = int(identity_block[1])
        if variant_raw == 0 and fut_config_raw == 0:
            raise NotFuturaDeviceError

        if profile_mode == PROFILE_MODE_AUTO:
            resolved_profile = await _async_autodetect_profile(client, device_kwarg, unit_id)
        else:
            if profile_mode not in SUPPORTED_PROFILES:
                raise InvalidProfileError
            resolved_profile = profile_mode
            if not await _async_profile_probe(client, device_kwarg, unit_id, resolved_profile):
                raise InvalidProfileError

        return ValidationResult(
            host=host,
            port=port,
            unit_id=unit_id,
            requested_profile_mode=profile_mode,
            resolved_profile=resolved_profile,
            variant_raw=variant_raw,
            fut_config_raw=fut_config_raw,
        )
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass


async def _async_autodetect_profile(
    client: AsyncModbusTcpClient, device_kwarg: str, unit_id: int
) -> str:
    successful_profiles = [
        profile_id
        for profile_id in SUPPORTED_PROFILES
        if await _async_profile_probe(client, device_kwarg, unit_id, profile_id)
    ]
    if len(successful_profiles) != 1:
        raise InvalidProfileError
    return successful_profiles[0]


async def _async_profile_probe(
    client: AsyncModbusTcpClient, device_kwarg: str, unit_id: int, profile_id: str
) -> bool:
    profile = get_profile(profile_id)
    address, count = profile.profile_probe
    try:
        response = await client.read_holding_registers(
            address, count=count, **{device_kwarg: unit_id}
        )
    except ModbusException:
        return False
    return not response.isError()


async def _async_read_input_registers(
    client: AsyncModbusTcpClient,
    device_kwarg: str,
    unit_id: int,
    address: int,
    count: int,
) -> list[int]:
    try:
        response = await client.read_input_registers(
            address, count=count, **{device_kwarg: unit_id}
        )
    except ModbusException as err:
        raise CannotConnectError from err
    if response.isError():
        raise CannotConnectError
    return list(response.registers)


def make_entry_data(
    user_input: dict[str, Any], validation: ValidationResult
) -> dict[str, Any]:
    """Build config entry data from flow input and validation result."""
    return {
        CONF_HOST: validation.host,
        CONF_PORT: validation.port,
        CONF_UNIT_ID: validation.unit_id,
        CONF_PROFILE_MODE: str(user_input[CONF_PROFILE_MODE]),
        CONF_RESOLVED_PROFILE: validation.resolved_profile,
        CONF_SCAN_INTERVAL_S: int(user_input[CONF_SCAN_INTERVAL_S]),
    }


def _get_device_kwarg_name() -> str:
    signature = inspect.signature(AsyncModbusTcpClient.read_input_registers)
    return "device_id" if "device_id" in signature.parameters else "slave"


def _to_signed_16bit(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def _u32_from(block: list[int], base: int, address: int) -> int:
    index = address - base
    return (block[index] << 16) | block[index + 1]


def _u16_from(block: list[int], base: int, address: int) -> int:
    return int(block[address - base])


def _i16_from(block: list[int], base: int, address: int) -> int:
    return _to_signed_16bit(_u16_from(block, base, address))


def _find_block_for_address(blocks: dict[int, list[int]], address: int) -> tuple[int, list[int]]:
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


def _read_input_i16(
    blocks: dict[int, list[int]], profile: RegisterProfile, key: str
) -> int:
    address = profile.input_address(key)
    base, block = _find_block_for_address(blocks, address)
    return _i16_from(block, base, address)


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
