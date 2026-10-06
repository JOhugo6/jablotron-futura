"""Configuration-owned external sensor presentation without deleting identities."""

from __future__ import annotations

import asyncio
import logging
import re
from copy import deepcopy
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .identity import make_device_identifier
from .models import FuturaConfigEntry
from .persistence import async_flush_entity_registry, async_save_store

_LOGGER = logging.getLogger(__name__)
METRICS = ("temperature", "humidity", "co2", "floor_temperature")
_SUFFIX = re.compile(
    r"_ext_sens_(temperature|humidity|co2|floor_temperature|present)_([1-8])$"
)


def eligible_metrics(config: dict[str, Any], slot: int) -> tuple[str, ...]:
    """Committed configuration alone defines relevance, independent of faults."""
    row = config["sensor_slots"].get(str(slot), {})
    if not row.get("enabled") or row.get("mode", "none") == "none":
        return ()
    if row["mode"] == "read":
        return (*METRICS, "present")
    return tuple(metric for metric in METRICS if row.get(f"{metric}_entity_id")) + (
        "present",
    )


def registry_metric(row: Any, entry_id: str) -> tuple[int, str] | None:
    """Match only external SENSOR identities belonging to this entry/platform."""
    if row.config_entry_id != entry_id or row.platform != DOMAIN:
        return None
    match = _SUFFIX.search(row.unique_id)
    if not match or row.domain != (
        "binary_sensor" if match[1] == "present" else "sensor"
    ):
        return None
    return int(match[2]), match[1]


class ExternalSensorVisibility:
    """Durably own default device associations; user assignments take precedence."""

    storage_name = "sensor_visibility"
    maximum_associations = 40

    def __init__(self, hass: HomeAssistant, entry: FuturaConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self.config = entry.runtime_data.coordinator.config
        self._registry = er.async_get(hass)
        self._devices = dr.async_get(hass)
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.{self.storage_name}")
        self._markers: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._remove_listener = None
        self._pending = False
        self._stopped = False
        self._valid = True
        self._journal_needs_save = False
        self.error_code: str | None = None

    def _identity_domain(self, identity: str) -> str | None:
        match = _SUFFIX.search(identity)
        if match is None:
            return None
        return "binary_sensor" if match[1] == "present" else "sensor"

    def _registry_position(self, row: Any) -> tuple[int, str] | None:
        return registry_metric(row, self.entry.entry_id)

    def _eligible(self, slot: int) -> tuple[str, ...]:
        return eligible_metrics(self.config, slot)

    def _marker_key(self, row: Any) -> str:
        return row.unique_id

    def _valid_marker_key(self, key: str) -> bool:
        return self._identity_domain(key) is not None

    def _matches_domain(self, identity: str, domain: str) -> bool:
        return domain == self._identity_domain(identity)

    def _journal_data(self, markers: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {"associations": markers}

    def _controller_id(self) -> str | None:
        identifier = (
            (DOMAIN, "controller_" + self.entry.data["identity_token"])
            if self.entry.data.get("identity_token")
            else make_device_identifier(self.entry.unique_id, self.entry.entry_id)
        )
        device = self._devices.async_get_device(identifiers={identifier})
        return device.id if device else None

    async def async_start(self) -> None:
        try:
            saved = await self._store.async_load()
            if saved is not None:
                self._load(saved)
        except (OSError, ValueError, TypeError, KeyError, HomeAssistantError):
            self._valid = False
            self._error("visibility_load_failed")
        await self.async_reconcile()
        self._remove_listener = self.hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, self._registry_changed
        )
        self.entry.async_on_unload(self._on_unload)

    def _load(self, saved: Any) -> None:
        if not isinstance(saved, dict) or set(saved) != {"associations"}:
            raise ValueError("visibility_shape")
        markers = saved["associations"]
        if not isinstance(markers, dict) or len(markers) > self.maximum_associations:
            raise ValueError("visibility_shape")
        for identity, marker in markers.items():
            if (
                not isinstance(identity, str)
                or not self._valid_marker_key(identity)
                or not isinstance(marker, dict)
                or set(marker)
                != {
                    "registry_id",
                    "original_device_id",
                    "suppressed",
                    "user_override",
                    "user_device_id",
                    "pending",
                }
                or not isinstance(marker["registry_id"], str)
                or not isinstance(marker["original_device_id"], (str, type(None)))
                or type(marker["suppressed"]) is not bool
                or type(marker["user_override"]) is not bool
                or type(marker["pending"]) is not bool
                or not isinstance(marker["user_device_id"], (str, type(None)))
                or (
                    not marker["user_override"] and marker["original_device_id"] is None
                )
            ):
                raise ValueError("visibility_marker")
        self._markers = deepcopy(markers)

    def _error(self, code: str) -> None:
        self.error_code = code
        _LOGGER.error(
            "External slot presentation failed (%s); registry identities retained",
            code,
        )

    @callback
    def _registry_changed(self, event: Event) -> None:
        if self._stopped:
            return
        row = self._registry.async_get(event.data["entity_id"])
        if row is None or self._registry_position(row) is None:
            return
        if event.data["action"] != "create" and "device_id" not in event.data.get(
            "changes", {}
        ):
            return
        self._pending = True
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_task(self._drain())

    async def _drain(self) -> None:
        while self._pending and not self._stopped:
            self._pending = False
            await self.async_reconcile()

    async def async_reconcile(self) -> None:
        """Save ownership before touching association; never touch transport or disable."""
        async with self._lock:
            if self._stopped or not self._valid:
                return
            controller = self._controller_id()
            proposed = deepcopy(self._markers)
            changes: list[tuple[Any, str | None]] = []
            identity_conflict = False
            incomplete = False
            mutation_failed = False
            for row in er.async_entries_for_config_entry(
                self._registry, self.entry.entry_id
            ):
                position = self._registry_position(row)
                if position is None:
                    continue
                slot, metric = position
                key = self._marker_key(row)
                marker = proposed.get(key)
                if marker is not None and marker["registry_id"] != row.id:
                    identity_conflict = True
                    continue
                if marker is None:
                    owns = controller is not None and row.device_id == controller
                    marker = proposed[key] = {
                        "registry_id": row.id,
                        "original_device_id": controller if owns else None,
                        "suppressed": False,
                        "user_override": not owns,
                        "user_device_id": None if owns else row.device_id,
                        "pending": False,
                    }
                expected = (
                    None if marker["suppressed"] else marker["original_device_id"]
                )
                if marker["pending"]:
                    if row.device_id != expected:
                        # An interrupted mutation has no proof of completion.
                        incomplete = True
                        continue
                    marker["pending"] = False
                if marker["user_override"] or row.device_id != expected:
                    marker["user_override"] = True
                    marker["user_device_id"] = row.device_id
                    continue
                suppress = metric not in self._eligible(slot)
                target = None if suppress else marker["original_device_id"]
                marker["suppressed"] = suppress
                if row.device_id != target:
                    marker["pending"] = True
                    changes.append((row, target))
            if proposed != self._markers or self._journal_needs_save:
                try:
                    await async_flush_entity_registry(self._registry)
                except (OSError, ValueError, TypeError, HomeAssistantError):
                    self._error("visibility_registry_save_failed")
                    return
                try:
                    await async_save_store(self._store, self._journal_data(proposed))
                except (OSError, ValueError, TypeError, HomeAssistantError):
                    self._error("visibility_save_failed")
                    return
                self._markers = proposed
                self._journal_needs_save = False
            # User registry changes can arrive while the ownership save awaits I/O.
            applied: list[str] = []
            for before, target in changes:
                current = self._registry.async_get(before.entity_id)
                if (
                    current is not None
                    and current.id == before.id
                    and current.device_id == before.device_id
                ):
                    try:
                        if (
                            target is not None
                            and self._devices.async_get(target) is None
                        ):
                            raise ValueError("device_missing")
                        self._registry.async_update_entity(
                            before.entity_id, device_id=target
                        )
                    except (ValueError, HomeAssistantError):
                        mutation_failed = True
                        continue
                    applied.append(self._marker_key(before))
                else:
                    marker = self._markers[self._marker_key(before)]
                    marker["pending"] = False
                    marker["user_override"] = True
                    marker["user_device_id"] = current.device_id if current else None
                    self._pending = True
            if changes:
                try:
                    await async_flush_entity_registry(self._registry)
                except (OSError, ValueError, TypeError, HomeAssistantError):
                    self._error("visibility_registry_save_failed")
                    return
                for identity in applied:
                    self._markers[identity]["pending"] = False
                try:
                    await async_save_store(
                        self._store, self._journal_data(deepcopy(self._markers))
                    )
                except (OSError, ValueError, TypeError, HomeAssistantError):
                    self._error("visibility_save_failed")
                    return
            if identity_conflict:
                self._error("visibility_identity_changed")
            elif incomplete:
                self._error("visibility_transition_incomplete")
            elif mutation_failed:
                self._error("visibility_registry_failed")
            else:
                self.error_code = None

    def device_info(
        self,
        identity: str,
        default: dr.DeviceInfo | None,
        domain: str | None = None,
    ) -> dr.DeviceInfo | None:
        """Keep HA's entity registration from overwriting an explicit association."""
        inferred_domain = self._identity_domain(identity)
        if domain is None:
            domain = inferred_domain
        if domain is None or not self._matches_domain(identity, domain):
            return default
        entity_id = self._registry.async_get_entity_id(domain, DOMAIN, identity)
        row = self._registry.async_get(entity_id) if entity_id else None
        if row is None:
            return default
        if self._registry_position(row) is None:
            return default
        marker = self._markers.get(self._marker_key(row))
        if (
            not self._valid
            or marker is None
            or marker["registry_id"] != row.id
            or marker["user_override"]
            or marker["suppressed"]
            or row.device_id != marker["original_device_id"]
        ):
            device = self._devices.async_get(row.device_id) if row.device_id else None
            if device:
                return dr.DeviceInfo(
                    identifiers=device.identifiers, connections=device.connections
                )
            return None
        return default

    @callback
    def _on_unload(self) -> Any:
        self._stopped = True
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        return self.async_stop()

    async def async_stop(self) -> None:
        self._stopped = True
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        if self._task is not None and self._task is not asyncio.current_task():
            await self._task
        # Await any reconciliation already doing a durable write before unloading.
        async with self._lock:
            self._pending = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "configured_count": sum(
                len(self._eligible(slot)) for slot in range(1, 9)
            ),
            "suppressed_count": sum(
                marker["suppressed"] and not marker["user_override"]
                for marker in self._markers.values()
            ),
            "user_override_count": sum(
                marker["user_override"] for marker in self._markers.values()
            ),
            "error_code": self.error_code,
            "listening": self._remove_listener is not None,
        }
