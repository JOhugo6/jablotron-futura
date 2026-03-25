"""Button platform for Jablotron Futura."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import FuturaEntity
from .models import FuturaConfigEntry

PARALLEL_UPDATES = 0


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

    def __init__(self, entry: FuturaConfigEntry, description: FuturaButtonDescription) -> None:
        super().__init__(
            entry.runtime_data.coordinator, entry, description.name, f"button_{description.key}"
        )
        self.description = description

    async def async_press(self) -> None:
        await self.coordinator.async_set_number_key(
            self.description.register_key,
            self.description.value,
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FuturaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [FuturaWriteButton(entry, description) for description in BUTTON_DESCRIPTIONS]
    )
