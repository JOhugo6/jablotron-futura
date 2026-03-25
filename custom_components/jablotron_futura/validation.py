"""Pure validation helpers used by config flow."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from .const import (
    CONF_BRIDGE_UPDATE_INTERVAL_S,
    CONF_FORCE_RESYNC_EVERY_S,
    CONF_STALE_AFTER_S,
)


class _EntryLike(Protocol):
    entry_id: str
    unique_id: str | None


def has_duplicate_unique_id(
    existing_entries: Iterable[_EntryLike],
    current_entry_id: str | None,
    candidate_unique_id: str,
) -> bool:
    """Return true if another entry already uses the same unique id."""
    return any(
        entry.entry_id != current_entry_id and entry.unique_id == candidate_unique_id
        for entry in existing_entries
    )


def validate_global_options(user_input: Mapping[str, Any]) -> dict[str, str]:
    """Validate global bridge options from the options flow."""
    errors: dict[str, str] = {}
    if int(user_input[CONF_BRIDGE_UPDATE_INTERVAL_S]) < 5:
        errors[CONF_BRIDGE_UPDATE_INTERVAL_S] = "bridge_interval_too_low"
    if int(user_input[CONF_STALE_AFTER_S]) < 10:
        errors[CONF_STALE_AFTER_S] = "stale_after_too_low"
    if int(user_input[CONF_FORCE_RESYNC_EVERY_S]) < 60:
        errors[CONF_FORCE_RESYNC_EVERY_S] = "force_resync_too_low"
    return errors
