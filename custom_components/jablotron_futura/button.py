"""Button platform for Jablotron Futura."""

from __future__ import annotations

from dataclasses import dataclass

import voluptuous as vol

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import UpdateFailed

from .entity import FuturaEntity
from .models import FuturaConfigEntry, eligible_button_members

PARALLEL_UPDATES = 0

SERVICE_ACTIVATE_EXTERNAL_BUTTON = "activate_external_button"
ATTR_DURATION_SECONDS = "duration_seconds"


@dataclass(frozen=True, kw_only=True)
class FuturaButtonDescription:
    key: str
    name: str
    register_key: str
    value: int


BUTTON_DESCRIPTIONS = (
    FuturaButtonDescription(
        key="boost_60",
        name="Start boost (60 min)",
        register_key="boost_remaining_s",
        value=60 * 60,
    ),
    FuturaButtonDescription(
        key="circulation_30",
        name="Start circulation (30 min)",
        register_key="circulation_remaining_s",
        value=30 * 60,
    ),
)


class FuturaWriteButton(FuturaEntity, ButtonEntity):
    """Button that writes a fixed value to one register."""

    def __init__(
        self, entry: FuturaConfigEntry, description: FuturaButtonDescription
    ) -> None:
        super().__init__(
            entry.runtime_data.coordinator,
            entry,
            description.name,
            f"button_{description.key}",
        )
        self.description = description

    async def async_press(self) -> None:
        await self.coordinator.async_set_number_key(
            self.description.register_key,
            self.description.value,
        )

    async def async_activate_external_button(self, duration_seconds: int) -> None:
        """Reject duration-based activation on fixed controller buttons."""
        raise HomeAssistantError(
            translation_domain="jablotron_futura", translation_key="slot_not_owned"
        )


class FuturaExternalButton(FuturaEntity, ButtonEntity):
    """An explicitly HA-owned slot, independent of physical discovery."""

    def __init__(self, entry: FuturaConfigEntry, slot: int) -> None:
        self._slot_index = slot
        config = entry.runtime_data.coordinator.config["button_slots"][str(slot)]
        super().__init__(
            entry.runtime_data.coordinator,
            entry,
            config["name"],
            config["entity_identity_suffix"],
        )
        if not config["name"]:
            del self._attr_name
            self._attr_translation_key = "external_button"
            self._attr_translation_placeholders = {"slot": str(slot)}

    @property
    def available(self) -> bool:
        buttons = self.coordinator.buttons
        return bool(
            super().available
            and not self.coordinator._frozen
            and not self.coordinator.config.get("migration_needs_repair")
            and buttons
            and buttons.states[str(self._slot_index)]["state"] in ("ready", "active")
        )

    async def async_press(self) -> None:
        await self._async_activate(None)

    async def async_activate_external_button(self, duration_seconds: int) -> None:
        await self._async_activate(duration_seconds)

    async def _async_activate(self, duration_seconds: int | None) -> None:
        try:
            await self.coordinator.buttons.activate(self._slot_index, duration_seconds)
        except (ValueError, UpdateFailed) as err:
            raise HomeAssistantError(
                translation_domain="jablotron_futura",
                translation_key=str(err),
            ) from err


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FuturaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_ACTIVATE_EXTERNAL_BUTTON,
        {
            vol.Required(ATTR_DURATION_SECONDS): vol.All(
                int, vol.Range(min=1, max=10800)
            )
        },
        "async_activate_external_button",
    )
    async_add_entities(
        [FuturaWriteButton(entry, description) for description in BUTTON_DESCRIPTIONS]
        + _build_external_button_entities(entry)
    )


def _build_external_button_entities(
    entry: FuturaConfigEntry,
) -> list[FuturaExternalButton]:
    return [
        FuturaExternalButton(entry, int(slot))
        for slot, config in entry.runtime_data.coordinator.config[
            "button_slots"
        ].items()
        if "action" in eligible_button_members(entry.runtime_data.coordinator.config, int(slot))
    ]
