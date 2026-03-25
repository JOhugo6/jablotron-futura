"""Shared entity helpers for Jablotron Futura."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import FuturaCoordinator
from .identity import make_device_identifier, make_device_name, make_entity_unique_id
from .models import FuturaConfigEntry


class FuturaEntity(CoordinatorEntity[FuturaCoordinator]):
    """Base entity class backed by the Futura coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FuturaCoordinator,
        entry: FuturaConfigEntry,
        name: str,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = name
        self._attr_unique_id = make_entity_unique_id(
            entry.unique_id,
            entry.entry_id,
            unique_suffix,
        )
        self._attr_device_info = DeviceInfo(
            identifiers={make_device_identifier(entry.unique_id, entry.entry_id)},
            manufacturer="Jablotron",
            model=coordinator.profile.profile_label,
            name=make_device_name(coordinator.unit_id),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose resolved profile on all entities for easier support."""
        return {
            "resolved_profile": self.coordinator.profile.profile_id,
        }
