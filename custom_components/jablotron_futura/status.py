"""Documented read-only mode/error/warning status bitmaps."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


MODE_BITS = {
    0: "Boost active",
    1: "Circulation active",
    2: "Time program active",
    3: "Overpressure active",
    4: "Away active",
    5: "Party active",
    6: "Night mode active",
    7: "Antiradon active",
    8: "Device running",
    9: "Filter check",
    10: "Drying",
    11: "Bypass open",
    12: "Ventilation limited by low outdoor temperature",
    13: "Stopped after error",
    14: "Device starting",
    15: "Service mode active",
    16: "Waste air below -3 degrees Celsius",
    17: "Frost protection active",
    18: "Emergency shutdown",
    19: "Duct pressure-loss measurement",
    20: "Stand-by",
    21: "Zone boost",
    22: "Zone pressure-loss measurement",
    23: "Heat exchanger defrosting",
}

ERROR_BITS = {
    0: "Ambient sensor error",
    1: "Indoor sensor error",
    2: "Fresh air sensor error",
    3: "Waste air sensor error",
    4: "Supply fan error",
    5: "Extract fan error",
    6: "Heat exchanger communication error",
    7: "Heat exchanger damper error",
    8: "IO board communication error",
    9: "Supply fan blocked",
    10: "Extract fan blocked",
    11: "CoolBreeze communication error",
    12: "CoolBreeze outdoor unit error",
    13: "Supply airflow below declared value",
    14: "Extract airflow below declared value",
    15: "CoolBreeze detected; duct analysis required",
    16: "VarioBreeze configuration changed; duct analysis required (bit 16)",
    17: "VarioBreeze configuration changed; duct analysis required (bit 17)",
    18: "Indoor humidity above limit",
    19: "CoolBreeze temperature sensor error",
    20: "Fan control failed",
    21: "Fresh air temperature too low",
}

WARNING_BITS = {
    0: "Filter not initialized",
    1: "Filter heavily clogged",
    2: "Filter used too long",
    3: "RTC battery low",
    4: "Supply fan speed too high",
    5: "Extract fan speed too high",
    8: "Low outdoor temperature warning",
    9: "Supply zone configuration warning",
    10: "Extract zone configuration warning",
    11: "Emergency shutdown",
    12: "SuperBreeze communication error",
    13: "General SuperBreeze error",
    14: "Power supply error",
    15: "VarioBreeze damper error",
    16: "Indoor humidity above limit",
    17: "Regular service inspection due",
}

STATUS_REGISTERS = {
    "modes_bits_raw": 16,
    "errors_bits_raw": 18,
    "warnings_bits_raw": 20,
}
STATUS_BITS = {
    "modes_bits_raw": MODE_BITS,
    "errors_bits_raw": ERROR_BITS,
    "warnings_bits_raw": WARNING_BITS,
}


def valid_status_value(value: Any) -> bool:
    """Do not turn missing, malformed or boolean values into an all-clear."""
    return type(value) is int and 0 <= value <= 0xFFFFFFFF


def decode_status_words(words: Sequence[int]) -> int:
    """Status pairs 16/17, 18/19 and 20/21 carry the low word first."""
    if (
        not isinstance(words, (list, tuple))
        or len(words) != 2
        or any(type(word) is not int or not 0 <= word <= 0xFFFF for word in words)
    ):
        raise ValueError("invalid_status_words")
    return words[0] | (words[1] << 16)


def status_details(value: Any, definitions: Mapping[int, str]) -> dict[str, Any]:
    """Classify known and reserved/unknown bits without masking the summary."""
    if not valid_status_value(value):
        return {
            "valid": False,
            "raw": None,
            "active_bits": [],
            "known_active_bits": [],
            "unknown_bits": [],
            "unknown_bits_mask": None,
        }
    active = [bit for bit in range(32) if value & (1 << bit)]
    unknown = [bit for bit in active if bit not in definitions]
    return {
        "valid": True,
        "raw": value,
        "active_bits": active,
        "known_active_bits": [bit for bit in active if bit in definitions],
        "unknown_bits": unknown,
        "unknown_bits_mask": sum(1 << bit for bit in unknown),
    }
