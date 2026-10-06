"""Strict, shared decoders for external holding blocks."""

from __future__ import annotations

from typing import Any


def valid_words(words: list[int], count: int) -> bool:
    return len(words) == count and all(
        type(word) is int and 0 <= word <= 65535 for word in words
    )


def decode_sensor(words: list[int]) -> dict[str, Any]:
    """Decode a whole FC3 block; absent measurements are never valid zeroes."""
    if not valid_words(words, 6) or words[0] not in (0, 1):
        raise ValueError("invalid_sensor_block")
    result: dict[str, Any] = {
        "present": bool(words[0]),
        "invalidate_mask": words[1],
        "unknown_invalid_bits": words[1] & 0xFFF0,
        "raw": list(words),
    }
    for bit, (metric, scale, low, high) in enumerate(
        (
            ("temperature", 10, -20, 100),
            ("humidity", 1, 0, 100),
            ("co2", 1, 0, 10000),
            ("floor_temperature", 10, -20, 100),
        )
    ):
        raw = words[bit + 2]
        if scale == 10 and raw & 0x8000:
            raw -= 65536
        value = raw / scale
        result[metric] = (
            value
            if words[0] and not words[1] & (1 << bit) and low <= value <= high
            else None
        )
    return result


def decode_button(words: list[int]) -> dict[str, Any]:
    """Decode a whole button block, rejecting malformed enum/timer values."""
    if (
        not valid_words(words, 4)
        or words[0] not in (0, 1)
        or words[1] not in (0, 1)
        or words[2] > 10800
        or words[3] not in (0, 1)
    ):
        raise ValueError("invalid_button_block")
    return {
        "present": bool(words[0]),
        "mode": words[1],
        "raw": list(words),
        "remaining_seconds": words[2] if words[0] else None,
        "active": bool(words[3]) if words[0] else None,
    }
