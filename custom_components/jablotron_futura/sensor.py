"""Sensor platform for Jablotron Futura."""

from __future__ import annotations


from dataclasses import dataclass


from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)

from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfVolumeFlowRate,
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from homeassistant.helpers.entity_platform import AddEntitiesCallback


from .entity import FuturaEntity

from .models import FuturaConfigEntry
from .sensor_visibility import METRICS, eligible_metrics
from .sensor_names import external_sensor_name_translation
from .models import eligible_button_members


PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class FuturaSensorDescription(SensorEntityDescription):
    key: str

    available_key: str | None = None


SENSOR_DESCRIPTIONS: tuple[FuturaSensorDescription, ...] = (
    FuturaSensorDescription(
        key="temp_outdoor",
        name="Outdoor temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="temp_supply",
        name="Supply temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="temp_extract",
        name="Extract temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="temp_exhaust",
        name="Exhaust temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="temp_outdoor_ntc",
        name="Outdoor NTC temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="humi_outdoor",
        name="Outdoor humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="humi_supply",
        name="Supply humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="humi_extract",
        name="Extract humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="humi_exhaust",
        name="Exhaust humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="filter_wear",
        name="Filter wear",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="power",
        name="Power draw",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="heat_recovering",
        name="Recovered heat",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="heating_power",
        name="Heating power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="air_flow",
        name="Air flow",
        native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="fan_power_supply_raw",
        name="Supply fan raw",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="fan_power_exhaust_raw",
        name="Exhaust fan raw",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="fan_rpm_supply",
        name="Supply fan RPM",
        native_unit_of_measurement="rpm",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="fan_rpm_exhaust",
        name="Exhaust fan RPM",
        native_unit_of_measurement="rpm",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(
        key="rtc_batt_voltage",
        name="RTC battery voltage",
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FuturaSensorDescription(key="mode_text", name="Ventilation mode"),
    FuturaSensorDescription(
        key="temp_set_raw",
        name="Temperature setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    FuturaSensorDescription(
        key="humi_set_raw",
        name="Humidity setpoint",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
    ),
    FuturaSensorDescription(key="boost_remaining_min", name="Boost minutes remaining"),
    FuturaSensorDescription(
        key="circulation_remaining_min", name="Circulation minutes remaining"
    ),
    FuturaSensorDescription(key="night_remaining_h", name="Night hours remaining"),
    FuturaSensorDescription(key="party_remaining_h", name="Party hours remaining"),
    FuturaSensorDescription(key="away_begin_text", name="Away begin"),
    FuturaSensorDescription(key="away_end_text", name="Away end"),
    FuturaSensorDescription(key="alfa_count", name="ALFA count"),
)


class FuturaSimpleSensor(FuturaEntity, SensorEntity):
    """Coordinator-backed sensor."""

    entity_description: FuturaSensorDescription

    def __init__(
        self,
        entry: FuturaConfigEntry,
        description: FuturaSensorDescription,
    ) -> None:

        super().__init__(
            entry.runtime_data.coordinator, entry, description.name, description.key
        )

        self.entity_description = description

    @property
    def device_info(self) -> DeviceInfo | None:
        discovery = getattr(self._entry.runtime_data, "alfa_discovery", None)
        if discovery is not None and discovery.is_detached(self.unique_id):
            return None
        if discovery is not None and (
            assigned := discovery.reassigned_device_info(self.unique_id)
        ):
            return assigned
        return super().device_info

    @property
    def native_value(self) -> float | int | str | None:

        return self.coordinator.data.get(self.entity_description.key)

    @property
    def available(self) -> bool:

        available_key = self.entity_description.available_key

        if available_key is None:
            return super().available

        return super().available and bool(
            self.coordinator.data.get(available_key, False)
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FuturaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:

    entities: list[SensorEntity] = [
        FuturaSimpleSensor(entry, description) for description in SENSOR_DESCRIPTIONS
    ]

    # Add Futura-managed button timer sensors

    entities.extend(_build_futura_button_timer_entities(entry))

    entities.extend(
        FuturaSlotSensor(entry, slot, metric)
        for slot in range(1, 9)
        for metric in eligible_metrics(entry.runtime_data.coordinator.config, slot)
        if metric in METRICS
    )

    async_add_entities(entities)
    from .alfa_discovery import AlfaDiscovery

    discovery = AlfaDiscovery(
        hass,
        entry,
        lambda slots: async_add_entities(_build_alfa_entities(entry, list(slots))),
    )
    entry.runtime_data.alfa_discovery = discovery
    await discovery.async_start()


def _build_alfa_entities(
    entry: FuturaConfigEntry, slots: list[int]
) -> list[SensorEntity]:
    """Preserve the six original suffixes and measurement semantics per position."""
    entities: list[SensorEntity] = []
    for slot_index in slots:
        available_key = f"alfa_{slot_index}_available"

        prefix = f"ALFA {slot_index}"

        entities.extend(
            [
                FuturaSimpleSensor(
                    entry,
                    FuturaSensorDescription(
                        key=f"alfa_mb_address_{slot_index}",
                        name=f"{prefix} address",
                        available_key=available_key,
                    ),
                ),
                FuturaSimpleSensor(
                    entry,
                    FuturaSensorDescription(
                        key=f"alfa_options_{slot_index}",
                        name=f"{prefix} options",
                        available_key=available_key,
                    ),
                ),
                FuturaSimpleSensor(
                    entry,
                    FuturaSensorDescription(
                        key=f"alfa_temp_{slot_index}",
                        name=f"{prefix} temperature",
                        available_key=available_key,
                        device_class=SensorDeviceClass.TEMPERATURE,
                        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                    ),
                ),
                FuturaSimpleSensor(
                    entry,
                    FuturaSensorDescription(
                        key=f"alfa_humi_{slot_index}",
                        name=f"{prefix} humidity",
                        available_key=available_key,
                        device_class=SensorDeviceClass.HUMIDITY,
                        native_unit_of_measurement=PERCENTAGE,
                    ),
                ),
                FuturaSimpleSensor(
                    entry,
                    FuturaSensorDescription(
                        key=f"alfa_co2_{slot_index}",
                        name=f"{prefix} CO2",
                        available_key=available_key,
                        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
                    ),
                ),
                FuturaSimpleSensor(
                    entry,
                    FuturaSensorDescription(
                        key=f"alfa_ntc_temp_{slot_index}",
                        name=f"{prefix} NTC temperature",
                        available_key=available_key,
                        device_class=SensorDeviceClass.TEMPERATURE,
                        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                    ),
                ),
            ]
        )

    return entities


class FuturaSlotSensor(FuturaEntity, SensorEntity):
    """Measurements from strict, independently scheduled holding readback."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, entry: FuturaConfigEntry, slot: int, metric: str, kind: str = "sensor"
    ) -> None:

        suffix = (
            f"ext_btn_tm_{slot}" if kind == "button" else f"ext_sens_{metric}_{slot}"
        )

        super().__init__(entry.runtime_data.coordinator, entry, "", suffix)

        self._slot, self._metric, self._kind = slot, metric, kind

        del self._attr_name

        if kind == "button":
            self._attr_translation_key = "external_button_timer"
            self._attr_translation_placeholders = {"slot": str(slot)}
        else:
            self._attr_translation_key, self._attr_translation_placeholders = (
                external_sensor_name_translation(
                    self.coordinator.config, slot, f"external_{metric}"
                )
            )

        self._attr_native_unit_of_measurement = {
            "temperature": "°C",
            "floor_temperature": "°C",
            "humidity": "%",
            "co2": "ppm",
            "remaining_seconds": "s",
        }[metric]

        self._attr_device_class = {
            "temperature": SensorDeviceClass.TEMPERATURE,
            "floor_temperature": SensorDeviceClass.TEMPERATURE,
            "humidity": SensorDeviceClass.HUMIDITY,
            "co2": SensorDeviceClass.CO2,
            "remaining_seconds": SensorDeviceClass.DURATION,
        }[metric]

    @property
    def available(self) -> bool:

        return (
            self.coordinator.readback_available(self._kind, self._slot)
            and self.native_value is not None
        )

    @property
    def native_value(self) -> float | int | str | None:

        states = (
            self.coordinator.sensor_readback
            if self._kind == "sensor"
            else self.coordinator.button_readback
        )

        return states.get(str(self._slot), {}).get(self._metric)


def _build_futura_button_timer_entities(
    entry: FuturaConfigEntry,
) -> list[FuturaSlotSensor]:

    return [
        FuturaSlotSensor(entry, slot, "remaining_seconds", "button")
        for slot in range(1, 9)
        if "timer" in eligible_button_members(entry.runtime_data.coordinator.config, slot)
    ]
