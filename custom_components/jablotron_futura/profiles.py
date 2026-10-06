"""Register profile definitions for Jablotron Futura."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from .const import PROFILE_FUTURA_LMS

STANDARD_INPUT_SEGMENTS: Final[tuple[tuple[int, int], ...]] = (
    (14, 8),
    (30, 4),
    (34, 5),
    (40, 9),
    (52, 1),
    (75, 1),
)

STANDARD_HOLDING_SEGMENT: Final[tuple[int, int]] = (0, 18)
ALFA_START: Final = 160
ALFA_SLOT_SIZE: Final = 10
ALFA_READ_COUNT: Final = 6

STANDARD_INPUT_KEYS: Final[dict[str, int]] = {
    "fact_device_id": 0,
    "fact_serial_number": 1,
    "fact_ethernet_mac": 3,
    "fact_hw_revision": 6,
    "firm_revision": 8,
    "variant_raw": 14,
    "fut_config_raw": 15,
    "modes_bits_raw": 16,
    "errors_bits_raw": 18,
    "warnings_bits_raw": 20,
    "temp_outdoor": 30,
    "temp_supply": 31,
    "temp_extract": 32,
    "temp_exhaust": 33,
    "humi_outdoor": 34,
    "humi_supply": 35,
    "humi_extract": 36,
    "humi_exhaust": 37,
    "temp_outdoor_ntc": 38,
    "filter_wear": 40,
    "power": 41,
    "heat_recovering": 42,
    "heating_power": 43,
    "air_flow": 44,
    "fan_power_supply_raw": 45,
    "fan_power_exhaust_raw": 46,
    "fan_rpm_supply": 47,
    "fan_rpm_exhaust": 48,
    "rtc_batt_voltage": 52,
    "connected_supply_valves_bits": 70,
    "connected_exhaust_valves_bits": 72,
    "connected_button_bits": 74,
    "alfa_connected_bits": 75,
    "vzv_identify_bits": 80,
}

STANDARD_HOLDING_KEYS: Final[dict[str, int]] = {
    "mode_raw": 0,
    "boost_remaining_s": 1,
    "circulation_remaining_s": 2,
    "overpressure_remaining_s": 3,
    "night_remaining_s": 4,
    "party_remaining_s": 5,
    "away_begin_ts": 6,
    "away_end_ts": 8,
    "temp_set_raw": 10,
    "humi_set_raw": 11,
    "time_program_raw": 12,
    "antiradon_raw": 13,
    "bypass_enable_raw": 14,
    "heating_enable_raw": 15,
    "cooling_enable_raw": 16,
    "comfort_enable_raw": 17,
}


@dataclass(frozen=True, slots=True)
class RegisterProfile:
    """A single supported register profile."""

    profile_id: str
    profile_label: str
    ext_sensor_slot1_base: int
    ext_button_slot1_base: int
    standard_input_segments: tuple[tuple[int, int], ...] = STANDARD_INPUT_SEGMENTS
    standard_holding_segment: tuple[int, int] = STANDARD_HOLDING_SEGMENT
    standard_input_keys: dict[str, int] = field(
        default_factory=lambda: dict(STANDARD_INPUT_KEYS)
    )
    standard_holding_keys: dict[str, int] = field(
        default_factory=lambda: dict(STANDARD_HOLDING_KEYS)
    )
    alfa_start: int = ALFA_START
    alfa_slot_size: int = ALFA_SLOT_SIZE
    alfa_read_count: int = ALFA_READ_COUNT

    @property
    def input_segments(self) -> tuple[tuple[int, int], ...]:
        return self.standard_input_segments

    @property
    def holding_segment(self) -> tuple[int, int]:
        return self.standard_holding_segment

    @property
    def profile_probe(self) -> tuple[int, int]:
        return (self.ext_sensor_slot1_base, 6)

    def input_address(self, key: str) -> int:
        """Return the address of one standard input register key."""
        return self.standard_input_keys[key]

    def holding_address(self, key: str) -> int:
        """Return the address of one standard holding register key."""
        return self.standard_holding_keys[key]

    def external_sensor_base(self, slot_index: int) -> int:
        if slot_index < 1 or slot_index > 8:
            raise ValueError(f"Unsupported external sensor slot: {slot_index}")
        return self.ext_sensor_slot1_base + (slot_index - 1) * 10

    def external_sensor_block(self, slot_index: int) -> tuple[int, int]:
        return (self.external_sensor_base(slot_index), 6)

    def external_button_base(self, slot_index: int) -> int:
        if slot_index < 1 or slot_index > 8:
            raise ValueError(f"Unsupported external button slot: {slot_index}")
        return self.ext_button_slot1_base + (slot_index - 1) * 10

    def external_button_block(self, slot_index: int) -> tuple[int, int]:
        return (self.external_button_base(slot_index), 4)

    def alfa_block(self, slot_index: int) -> tuple[int, int]:
        """Return the register block for one ALFA sensor slot."""
        if slot_index < 1 or slot_index > 8:
            raise ValueError(f"Unsupported ALFA slot: {slot_index}")
        return (
            self.alfa_start + (slot_index - 1) * self.alfa_slot_size,
            self.alfa_read_count,
        )


PROFILES: Final[dict[str, RegisterProfile]] = {
    PROFILE_FUTURA_LMS: RegisterProfile(
        profile_id=PROFILE_FUTURA_LMS,
        profile_label="Futura L/M/S",
        ext_sensor_slot1_base=300,
        ext_button_slot1_base=400,
    ),
}


def get_profile(profile_id: str) -> RegisterProfile:
    """Return one known register profile."""
    return PROFILES[profile_id]
