from collections.abc import Callable
from dataclasses import dataclass
from logging import getLogger
from typing import Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    STATE_UNAVAILABLE,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import VehicleCoordinator, get_all_coordinators
from .const import DOMAIN, SEAT_STATUS
from .vehicle_coordinator_base_entity import VehicleCoordinatorBaseEntity

_LOGGER = getLogger(__name__)
PARALLEL_UPDATES: int = 1
HEAT_VENT_TYPE = "heatVentType"


@dataclass(frozen=True)
class KiaSensorEntityDescription(SensorEntityDescription):
    """A class that describes custom sensor entities."""

    preserve_state: bool = False
    exists_fn: Callable[[VehicleCoordinator], bool] = lambda _: True


SENSOR_DESCRIPTIONS: Final[tuple[KiaSensorEntityDescription, ...]] = (
    KiaSensorEntityDescription(
        key="ev_battery_level",
        name="EV Battery",
        icon="mdi:car-electric",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        preserve_state=True,
    ),
    KiaSensorEntityDescription(
        key="odometer_value",
        name="Odometer",
        icon="mdi:speedometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.MILES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    KiaSensorEntityDescription(
        key="last_synced_to_cloud",
        name="Last Synced To Cloud",
        icon="mdi:update",
        device_class=SensorDeviceClass.TIMESTAMP,
        native_unit_of_measurement=None,
    ),
    KiaSensorEntityDescription(
        key="last_synced_from_cloud",
        name="Last Synced from Cloud",
        icon="mdi:update",
        device_class=SensorDeviceClass.TIMESTAMP,
        native_unit_of_measurement=None,
    ),
    KiaSensorEntityDescription(
        key="next_service_mile_value",
        name="Next Service Mile",
        icon="mdi:car-wrench",
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=0,
        native_unit_of_measurement=UnitOfLength.MILES,
        state_class=SensorStateClass.TOTAL,
    ),
    KiaSensorEntityDescription(
        key="climate_temperature_value",
        name="Set Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
    ),
    KiaSensorEntityDescription(
        key="ev_charge_current_remaining_duration",
        name="Estimated Current Charge Duration",
        device_class=SensorDeviceClass.DURATION,
        icon="mdi:ev-station",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    KiaSensorEntityDescription(
        key="ev_remaining_range_value",
        name="Range by EV",
        device_class=SensorDeviceClass.DISTANCE,
        icon="mdi:road-variant",
        native_unit_of_measurement=UnitOfLength.MILES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    KiaSensorEntityDescription(
        key="fuel_level",
        name="Fuel Level",
        icon="mdi:fuel",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    KiaSensorEntityDescription(
        key="fuel_remaining_range_value",
        name="Range by Fuel",
        device_class=SensorDeviceClass.DISTANCE,
        icon="mdi:road-variant",
        native_unit_of_measurement=UnitOfLength.MILES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    KiaSensorEntityDescription(
        key="total_remaining_range_value",
        name="Range Total",
        device_class=SensorDeviceClass.DISTANCE,
        icon="mdi:road-variant",
        native_unit_of_measurement=UnitOfLength.MILES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    KiaSensorEntityDescription(
        key="car_battery_level",
        name="12v Battery",
        device_class=None,
        icon="mdi:car-battery",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        preserve_state=True
    ),
)

SEAT_SENSOR_DESCRIPTIONS: Final[tuple[KiaSensorEntityDescription, ...]] = (
    KiaSensorEntityDescription(
        key="climate_driver_seat",
        name="Seat-Driver",
        exists_fn=lambda seat: True,  # Existence checked by has_climate_seats
    ),
    KiaSensorEntityDescription(
        key="climate_passenger_seat",
        name="Seat-Passenger",
        exists_fn=lambda seat: True,  # Existence checked by has_climate_seats
    ),
    KiaSensorEntityDescription(
        key="climate_left_rear_seat",
        name="Seat-Left Rear",
        exists_fn=lambda seat: bool(seat.rear_seat_options.get(HEAT_VENT_TYPE, 0)),  # Rear may not exist
    ),
    KiaSensorEntityDescription(
        key="climate_right_rear_seat",
        name="Seat-Right Rear",
        exists_fn=lambda seat: bool(seat.rear_seat_options.get(HEAT_VENT_TYPE, 0)),  # Rear may not exist
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinators = get_all_coordinators(hass)
    
    sensors: list[SensorEntity] = []
    
    for coordinator in coordinators.values():
        sensors.append(APIActionInProgress(coordinator=coordinator))
        
        for sensor_description in SENSOR_DESCRIPTIONS:
            _LOGGER.debug(f"Adding sensor {sensor_description.key}? preserve_state:{sensor_description.preserve_state is True} or value:{getattr(coordinator, sensor_description.key)} is not None:{getattr(coordinator, sensor_description.key) is not None}")
            if sensor_description.preserve_state or getattr(coordinator, sensor_description.key) is not None:
                _LOGGER.debug(f"added {sensor_description.key}")
                sensors.append(
                    InstrumentSensor(
                        coordinator,
                        sensor_description,
                    )
                )
        sensors.extend(
            SeatSensor(coordinator, seat_description)
            for seat_description in SEAT_SENSOR_DESCRIPTIONS
            if coordinator.has_climate_seats
            if seat_description.exists_fn(coordinator)
        )

    async_add_entities(sensors)


class InstrumentSensor(VehicleCoordinatorBaseEntity, SensorEntity, RestoreEntity):
    @property
    def native_value(self):
        value = getattr(self.coordinator, self.entity_description.key)
        if value is not None and value != 0:
            self._attr_native_value = value
        return self._attr_native_value

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self.native_value is not None

    async def async_internal_added_to_hass(self) -> None:
        """Call when the button is added to hass."""
        await super().async_internal_added_to_hass()
        if self.entity_description.preserve_state:
            state = await self.async_get_last_state()
            if state is not None and state.state not in (STATE_UNAVAILABLE, None):
                self.__set_state(state.state)

    def __set_state(self, state: str | None) -> None:
        """Set the entity state."""
        # Invalidate the cache of the cached property
        self.__dict__.pop("state", None)
        self._attr_native_value = state


class SeatSensor(VehicleCoordinatorBaseEntity, SensorEntity):
    """Class for seat sensors."""

    @property
    def native_value(self) -> str:
        """Return the state of the seat."""
        return SEAT_STATUS[getattr(self.coordinator, self.entity_description.key)]

    @property
    def available(self) -> bool:
        """Return if the sensor is available."""
        return super().available and self.native_value is not None

    @property
    def icon(self) -> str:
        """Return an icon based on the seat state."""
        if "Heat" in self.native_value:
            return "mdi:car-seat-heater"
        if "Cool" in self.native_value:
            return "mdi:car-seat-cooler"
        return "mdi:car-seat"


class APIActionInProgress(VehicleCoordinatorBaseEntity, SensorEntity):
    def __init__(self, coordinator: VehicleCoordinator):
        super().__init__(coordinator, SensorEntityDescription(
            key="last_action_name",
            name="API Action In Progress",
            device_class=SensorDeviceClass.ENUM,
        ))

    @property
    def icon(self):
        return "mdi:api-off" if self.coordinator.last_action_name is None else "mdi:api"

    @property
    def native_value(self):
        """Return the value reported by the sensor."""
        return self.coordinator.last_action_name if self.coordinator.last_action_name is not None else "None"
