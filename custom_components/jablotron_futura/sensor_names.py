"""Presentation-only translation selection for external sensor slots."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def external_sensor_name_translation(
    config: Mapping[str, Any], slot: int, generic_key: str
) -> tuple[str, dict[str, str]]:
    """Use a configured label, retaining localized defaults for legacy slots."""
    name = config.get("sensor_slots", {}).get(str(slot), {}).get("name")
    if isinstance(name, str) and name.strip():
        return f"named_{generic_key}", {"slot_name": name.strip()}
    return generic_key, {"slot": str(slot)}
