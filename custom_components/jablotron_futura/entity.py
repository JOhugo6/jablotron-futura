"""Shared entity helpers for Jablotron Futura."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import FuturaCoordinator
from .identity import make_device_identifier, make_device_name, make_entity_unique_id
from .models import DeviceIdentity
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
        if entry.data.get("identity_token"):
            self._attr_unique_id = f"{entry.data['identity_token']}_{unique_suffix}"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Build device metadata from the latest coordinator identity snapshot."""
        identity = DeviceIdentity.from_mapping(
            self.coordinator.data.get("device_identity", self._entry.data)
        )
        info: DeviceInfo | None = DeviceInfo(
            identifiers={
                ("jablotron_futura", "controller_" + self._entry.data["identity_token"])
            }
            if self._entry.data.get("identity_token")
            else {make_device_identifier(self._entry.unique_id, self._entry.entry_id)},
            manufacturer="Jablotron",
            model=identity.device_variant or self.coordinator.profile.profile_label,
            name=make_device_name(self.coordinator.unit_id),
            hw_version=identity.hardware_revision or None,
            sw_version=identity.firmware_revision or None,
            serial_number=identity.serial_number or None,
        )
        domain = getattr(getattr(self, "platform", None), "domain", None)
        if domain is None and (entity_id := getattr(self, "entity_id", None)):
            domain = entity_id.partition(".")[0]
        visibility = getattr(self._entry.runtime_data, "sensor_visibility", None)
        if visibility:
            info = visibility.device_info(self.unique_id, info, domain)
        visibility = getattr(self._entry.runtime_data, "button_visibility", None)
        return visibility.device_info(self.unique_id, info, domain) if visibility else info

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose resolved profile on all entities for easier support."""
        return {
            "resolved_profile": self.coordinator.profile.profile_id,
        }
