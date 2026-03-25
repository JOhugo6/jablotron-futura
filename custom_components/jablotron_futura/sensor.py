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
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import FuturaEntity
from .models import FuturaConfigEntry

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
    FuturaSensorDescription(key="circulation_remaining_min", name="Circulation minutes remaining"),
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
        super().__init__(entry.runtime_data.coordinator, entry, description.name, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def available(self) -> bool:
        available_key = self.entity_description.available_key
        if available_key is None:
            return super().available
        return super().available and bool(self.coordinator.data.get(available_key, False))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FuturaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[SensorEntity] = [
        FuturaSimpleSensor(entry, description) for description in SENSOR_DESCRIPTIONS
    ]

    for slot_index in range(1, 9):
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

    async_add_entities(entities)
