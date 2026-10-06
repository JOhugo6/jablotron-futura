"""Physical ALFA discovery from existing successful polls, with durable history."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .models import FuturaConfigEntry
from .persistence import async_save_store

_LOGGER = logging.getLogger(__name__)
ALFA_FIELDS = ("mb_address", "options", "temp", "humi", "co2", "ntc_temp")
_SUFFIX = re.compile(r"_alfa_(?:mb_address|options|temp|humi|co2|ntc_temp)_([1-8])$")
_LEGACY_CLEANUP_MARKER = "verified_demo_phantom_v1"
_CLEANUP_MARKER = "verified_demo_detached_v2"


def _has_custom_options(row: Any) -> bool:
    """Exclude only HA's measured default suggestion, never user precision/unit.

    HA2025.9 SensorEntity._update_suggested_precision writes this automatically
    for Celsius temperature entities. User-selected `display_precision` and
    every other option remain a reason to retain the row visibly.
    """
    if not row.options:
        return False
    return not (
        re.search(r"_alfa_(?:temp|ntc_temp)_[1-8]$", row.unique_id)
        and row.options == {"sensor": {"suggested_display_precision": 1}}
    )


def registry_slot(row: Any, entry_id: str) -> int | None:
    """Match only this entry's pre-existing physical ALFA sensor identities."""
    if (
        row.config_entry_id != entry_id
        or row.platform != DOMAIN
        or row.domain != "sensor"
    ):
        return None
    match = _SUFFIX.search(row.unique_id)
    return int(match[1]) if match else None


def observed_slots(coordinator: Any) -> set[int]:
    """A partial/failed snapshot is never evidence of a new physical device."""
    data = coordinator.data or {}
    bitmap = data.get("alfa_connected_bits")
    if (
        not coordinator.last_update_success
        or type(bitmap) is not int
        or not 0 <= bitmap <= 255
    ):
        return set()
    return {
        slot
        for slot in range(1, 9)
        if bitmap & (1 << (slot - 1))
        and data.get(f"alfa_{slot}_available") is True
        and all(
            type(data.get(f"alfa_{field}_{slot}")) in (int, float)
            for field in ALFA_FIELDS
        )
    }


class AlfaDiscovery:
    """Own one listener and persist only newly observed positions/visibility markers."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: FuturaConfigEntry,
        add_slots: Callable[[Iterable[int]], None],
    ) -> None:
        self.hass, self.entry = hass, entry
        self.runtime = entry.runtime_data
        self.coordinator = self.runtime.coordinator
        self._add_slots = add_slots
        self._registry = er.async_get(hass)
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.alfa_discovery")
        self.seen: set[int] = set()
        self.legacy_unknown: set[int] = set()
        self._added: set[int] = set()
        self._demo_hidden: dict[str, dict[str, Any]] = {}
        self._remove_listener: Callable[[], None] | None = None
        self._save_task: asyncio.Task | None = None
        self._save_lock = asyncio.Lock()
        self._revision = 0
        self._saved_revision = 0
        self._stopped = False
        self.history_status = "missing"
        self.error_code: str | None = None

    async def async_start(self) -> None:
        try:
            saved = await self._store.async_load()
            if saved is not None:
                self._load(saved)
        except (OSError, ValueError, TypeError, KeyError, HomeAssistantError):
            self.history_status = "invalid"
            self.error_code = "history_load_failed"
            _LOGGER.error(
                "ALFA observation history is invalid; retaining existing registry entities"
            )
        existing = {
            slot
            for row in er.async_entries_for_config_entry(
                self._registry, self.entry.entry_id
            )
            if (slot := registry_slot(row, self.entry.entry_id)) is not None
        }
        self.legacy_unknown = existing - self.seen
        self._add(existing | self.seen)
        self._update()
        self._remove_listener = self.coordinator.async_add_listener(self._update)
        self.entry.async_on_unload(self._on_unload)
        await self.async_flush()

    def _load(self, saved: Any) -> None:
        if not isinstance(saved, dict):
            raise ValueError("history_shape")
        slots = saved.get("observed_slots")
        hidden = saved.get("demo_hidden", {})
        if (
            not isinstance(slots, list)
            or len(slots) > 8
            or any(type(slot) is not int or not 1 <= slot <= 8 for slot in slots)
            or len(set(slots)) != len(slots)
            or not isinstance(hidden, dict)
            or len(hidden) > 48
        ):
            raise ValueError("history_shape")
        for identity, marker in hidden.items():
            if (
                not isinstance(identity, str)
                or not _SUFFIX.search(identity)
                or not isinstance(marker, dict)
                or marker.get("kind") not in (_LEGACY_CLEANUP_MARKER, _CLEANUP_MARKER)
                or not isinstance(marker.get("registry_id"), str)
                or not isinstance(marker.get("evidence_id"), str)
                or (
                    marker.get("kind") == _CLEANUP_MARKER
                    and not isinstance(marker.get("original_device_id"), str)
                )
            ):
                raise ValueError("history_marker")
        self.seen = set(slots)
        self._demo_hidden = hidden
        self.history_status = "restored"

    def _add(self, slots: set[int]) -> None:
        new = slots - self._added
        if new and not self._stopped:
            self._added.update(new)
            self._add_slots(sorted(new))

    @callback
    def _update(self) -> None:
        if self._stopped or self.runtime.transition_state != "active":
            return
        current = observed_slots(self.coordinator)
        changed = bool(current - self.seen)
        self.seen.update(current)
        self.legacy_unknown.difference_update(current)
        self._add(current)
        changed = self._reveal_observed(current) or changed
        if changed:
            self._revision += 1
            if self._save_task is None or self._save_task.done():
                self._save_task = self.hass.async_create_task(self.async_flush())

    def _reveal_observed(self, current: set[int]) -> bool:
        changed = False
        for identity, marker in list(self._demo_hidden.items()):
            entity_id = self._registry.async_get_entity_id("sensor", DOMAIN, identity)
            row = self._registry.async_get(entity_id) if entity_id else None
            if (
                row is None
                or row.id != marker["registry_id"]
                or registry_slot(row, self.entry.entry_id) not in current
            ):
                continue
            owns_device = marker["kind"] == _CLEANUP_MARKER
            updates = {}
            if owns_device and row.device_id is None:
                updates["device_id"] = marker["original_device_id"]
            # Restore our hiding without changing USER hiding or disabling.
            if (
                row.disabled_by is None or owns_device
            ) and row.hidden_by == er.RegistryEntryHider.INTEGRATION:
                updates["hidden_by"] = None
            if updates:
                self._registry.async_update_entity(row.entity_id, **updates)
            if owns_device and row.device_id not in (
                None,
                marker["original_device_id"],
            ):
                # Retain the marker as a device_info override across reloads;
                # the user's later device assignment supersedes our association.
                changed = bool(updates) or changed
                continue
            self._demo_hidden.pop(identity)
            changed = True
        return changed

    def is_detached(self, identity: str) -> bool:
        """Only suppress integration device_info while an owned phantom is detached."""
        marker = self._demo_hidden.get(identity)
        if not marker or marker["kind"] != _CLEANUP_MARKER:
            return False
        entity_id = self._registry.async_get_entity_id("sensor", DOMAIN, identity)
        row = self._registry.async_get(entity_id) if entity_id else None
        return bool(
            row
            and row.id == marker["registry_id"]
            and row.device_id is None
            and registry_slot(row, self.entry.entry_id) not in self.seen
        )

    def reassigned_device_info(self, identity: str) -> dr.DeviceInfo | None:
        marker = self._demo_hidden.get(identity)
        if not marker or marker["kind"] != _CLEANUP_MARKER:
            return None
        entity_id = self._registry.async_get_entity_id("sensor", DOMAIN, identity)
        row = self._registry.async_get(entity_id) if entity_id else None
        if (
            row
            and row.id == marker["registry_id"]
            and row.device_id not in (None, marker["original_device_id"])
        ):
            device = dr.async_get(self.hass).async_get(row.device_id)
            if device:
                return dr.DeviceInfo(
                    identifiers=device.identifiers, connections=device.connections
                )
        return None

    async def async_flush(self) -> None:
        async with self._save_lock:
            while self._saved_revision != self._revision:
                revision = self._revision
                payload = {
                    "observed_slots": sorted(self.seen),
                    "demo_hidden": dict(self._demo_hidden),
                }
                try:
                    await async_save_store(self._store, payload)
                except (OSError, ValueError, TypeError, HomeAssistantError):
                    self.error_code = "history_save_failed"
                    _LOGGER.error(
                        "ALFA observation history could not be saved; registry identities retained"
                    )
                    return
                self._saved_revision = revision
                self.error_code = None
                self.history_status = "saved"

    @callback
    def _on_unload(self) -> Any:
        self._stopped = True
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        return self.async_flush()

    async def async_stop(self) -> None:
        """Also usable by deterministic lifecycle tests; no future additions."""
        await self._on_unload()

    async def async_hide_verified_demo_phantoms(
        self, evidence: dict[str, str]
    ) -> list[str]:
        """Scoped maintenance hook; caller supplies an audited evidence ID per row.

        This is never called by setup, migration, a poll or a registered service.
        The authorized isolated-demo operator must independently establish no
        physical history or references; default names alone are not evidence.
        """
        candidates = []
        controller_devices = {
            row.device_id
            for row in er.async_entries_for_config_entry(
                self._registry, self.entry.entry_id
            )
            if registry_slot(row, self.entry.entry_id) is None and row.device_id
        }
        for entity_id, evidence_id in evidence.items():
            row = self._registry.async_get(entity_id)
            slot = registry_slot(row, self.entry.entry_id) if row else None
            marker = self._demo_hidden.get(row.unique_id) if row else None
            upgrade_owned_v1 = bool(
                marker
                and marker["kind"] == _LEGACY_CLEANUP_MARKER
                and marker["registry_id"] == row.id
                and row.hidden_by == er.RegistryEntryHider.INTEGRATION
            )
            if (
                not evidence_id
                or slot is None
                or slot in self.seen
                or slot in observed_slots(self.coordinator)
                or (marker is not None and not upgrade_owned_v1)
                or (row.hidden_by is not None and not upgrade_owned_v1)
                or row.disabled_by is not None
                or not row.device_id
                or len(controller_devices) != 1
                or row.device_id not in controller_devices
                or row.name
                or row.area_id
                or row.icon
                or row.labels
                or row.aliases
                or _has_custom_options(row)
            ):
                continue
            candidates.append(row)
            self._demo_hidden[row.unique_id] = {
                "kind": _CLEANUP_MARKER,
                "registry_id": row.id,
                "evidence_id": evidence_id,
                "original_device_id": row.device_id,
            }
        if not candidates:
            return []
        self._revision += 1
        await self.async_flush()
        if self.error_code:
            return []
        hidden = []
        skipped = False
        for row in candidates:
            current = self._registry.async_get(row.entity_id)
            if (
                current == row
                and registry_slot(current, self.entry.entry_id) not in self.seen
                and row.unique_id in self._demo_hidden
            ):
                self._registry.async_update_entity(
                    row.entity_id,
                    hidden_by=er.RegistryEntryHider.INTEGRATION,
                    device_id=None,
                )
                hidden.append(row.entity_id)
            elif self._demo_hidden.pop(row.unique_id, None) is not None:
                skipped = True
        if skipped:
            self._revision += 1
            await self.async_flush()
        return hidden

    def snapshot(self) -> dict[str, Any]:
        """Inspectable evidence; no network, entity IDs, names or areas exported."""
        return {
            "observed_slots": sorted(self.seen),
            "legacy_unknown_slots": sorted(self.legacy_unknown),
            "added_slots": sorted(self._added),
            "history_status": self.history_status,
            "error_code": self.error_code,
            "demo_hidden_count": len(self._demo_hidden),
            "listening": self._remove_listener is not None,
        }
