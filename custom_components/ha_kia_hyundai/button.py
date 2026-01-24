from logging import getLogger

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VehicleCoordinator, get_all_coordinators
from .const import DOMAIN
from .vehicle_coordinator_base_entity import VehicleCoordinatorBaseEntity

_LOGGER = getLogger(__name__)
PARALLEL_UPDATES: int = 1


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    coordinators = get_all_coordinators(hass)

    entities = []
    for coordinator in coordinators.values():
        entities.append(RequestUpdateFromCarButton(coordinator=coordinator))
        # Add remote start/stop buttons if vehicle supports climate
        if coordinator.can_remote_climate:
            entities.append(RemoteStartButton(coordinator=coordinator))
            entities.append(RemoteStopButton(coordinator=coordinator))
    
    async_add_entities(entities)


class RequestUpdateFromCarButton(VehicleCoordinatorBaseEntity, ButtonEntity):
    def __init__(
            self,
            coordinator: VehicleCoordinator,
    ):
        super().__init__(coordinator, ButtonEntityDescription(
            key="request_vehicle_data_sync",
            name="Request Wake Up from Car (hurts 12v battery)",
            device_class=ButtonDeviceClass.UPDATE,
        ))

    async def async_press(self) -> None:
        """Press the button."""
        await self.coordinator.api_connection.request_vehicle_data_sync(vehicle_id=self.coordinator.vehicle_id)
        self.coordinator.async_update_listeners()
        await self.coordinator.async_request_refresh()


class RemoteStartButton(VehicleCoordinatorBaseEntity, ButtonEntity):
    """Button to start vehicle with current climate settings."""

    def __init__(
            self,
            coordinator: VehicleCoordinator,
    ):
        super().__init__(coordinator, ButtonEntityDescription(
            key="remote_start",
            name="Remote Start",
            icon="mdi:car-key",
        ))

    async def async_press(self) -> None:
        """Start the vehicle with configured climate settings."""
        _LOGGER.info("===== REMOTE START BUTTON PRESSED =====")
        _LOGGER.info(
            "Starting with: temp=%s, defrost=%s, heating=%s, steering_wheel=%s",
            self.coordinator.desired_temperature,
            self.coordinator.climate_desired_defrost,
            self.coordinator.climate_desired_heating_acc,
            self.coordinator.desired_steering_wheel_heat,
        )
        _LOGGER.info(
            "Seat settings: driver=%s, passenger=%s, left_rear=%s, right_rear=%s",
            self.coordinator.desired_driver_seat_comfort,
            self.coordinator.desired_passenger_seat_comfort,
            self.coordinator.desired_left_rear_seat_comfort,
            self.coordinator.desired_right_rear_seat_comfort,
        )
        
        await self.coordinator.api_connection.start_climate(
            vehicle_id=self.coordinator.vehicle_id,
            climate=True,
            set_temp=self.coordinator.desired_temperature,
            defrost=self.coordinator.climate_desired_defrost,
            heating=self.coordinator.climate_desired_heating_acc,
            steering_wheel_heat=self.coordinator.desired_steering_wheel_heat,
            driver_seat=self.coordinator.desired_driver_seat_comfort,
            passenger_seat=self.coordinator.desired_passenger_seat_comfort,
            left_rear_seat=self.coordinator.desired_left_rear_seat_comfort,
            right_rear_seat=self.coordinator.desired_right_rear_seat_comfort,
        )
        self.coordinator.async_update_listeners()
        await self.coordinator.async_request_refresh()


class RemoteStopButton(VehicleCoordinatorBaseEntity, ButtonEntity):
    """Button to stop vehicle climate/engine."""

    def __init__(
            self,
            coordinator: VehicleCoordinator,
    ):
        super().__init__(coordinator, ButtonEntityDescription(
            key="remote_stop",
            name="Remote Stop",
            icon="mdi:car-off",
        ))

    async def async_press(self) -> None:
        """Stop the vehicle climate/engine."""
        _LOGGER.info("===== REMOTE STOP BUTTON PRESSED =====")
        await self.coordinator.api_connection.stop_climate(
            vehicle_id=self.coordinator.vehicle_id
        )
        self.coordinator.async_update_listeners()
        await self.coordinator.async_request_refresh()
