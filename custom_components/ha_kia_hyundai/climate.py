"""Create climate platform."""

from logging import getLogger
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
    PRECISION_WHOLE,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VehicleCoordinator, get_all_coordinators
from .vehicle_coordinator_base_entity import VehicleCoordinatorBaseEntity
from .const import (
    DOMAIN,
    TEMPERATURE_MIN,
    TEMPERATURE_MAX,
)

_LOGGER = getLogger(__name__)
SUPPORT_FLAGS = (
    ClimateEntityFeature.TURN_ON
    | ClimateEntityFeature.TURN_OFF
    | ClimateEntityFeature.TARGET_TEMPERATURE
)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    coordinators = get_all_coordinators(hass)
    
    entities = []
    for coordinator in coordinators.values():
        if coordinator.can_remote_climate:
            _LOGGER.debug("Adding climate entity for %s", coordinator.vehicle_name)
            entities.append(Thermostat(coordinator))
        else:
            _LOGGER.debug("Skipping climate entity for %s, can not remote start?", coordinator.vehicle_name)
    
    async_add_entities(entities)


class Thermostat(VehicleCoordinatorBaseEntity, ClimateEntity):
    """Create thermostat."""

    _attr_supported_features = SUPPORT_FLAGS
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator: VehicleCoordinator):
        """Create thermostat."""
        super().__init__(coordinator, ClimateEntityDescription(
            name="Climate",
            key="climate",
        ))
        self._attr_target_temperature = int(self.coordinator.climate_temperature_value)
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.HEAT_COOL,
        ]
        self._attr_target_temperature_step = PRECISION_WHOLE
        self._attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
        self._attr_max_temp = TEMPERATURE_MAX
        self._attr_min_temp = TEMPERATURE_MIN

    @property
    def hvac_mode(self) -> HVACMode | str | None:
        """Return hvac mode."""
        if self.coordinator.climate_hvac_on:
            return HVACMode.HEAT_COOL
        else:
            return HVACMode.OFF

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Update hvac mode."""
        _LOGGER.debug(f"set_hvac_mode; hvac_mode:{hvac_mode}")
        match hvac_mode.strip().lower():
            case HVACMode.OFF:
                await self.coordinator.api_connection.stop_climate(vehicle_id=self.coordinator.vehicle_id)
            case HVACMode.HEAT_COOL | HVACMode.AUTO:
                await self.coordinator.api_connection.start_climate(
                    vehicle_id=self.coordinator.vehicle_id,
                    climate=True,
                    set_temp=int(self.target_temperature),
                    defrost=self.coordinator.climate_desired_defrost,
                    heating=self.coordinator.climate_desired_heating_acc,
                    driver_seat=self.coordinator.desired_driver_seat_comfort,
                    passenger_seat=self.coordinator.desired_passenger_seat_comfort,
                    left_rear_seat=self.coordinator.desired_left_rear_seat_comfort,
                    right_rear_seat=self.coordinator.desired_right_rear_seat_comfort,
                )
        self.coordinator.async_update_listeners()
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        _LOGGER.debug(f"set_temperature; kwargs:{kwargs}")
        self._attr_target_temperature = kwargs.get(ATTR_TEMPERATURE)
        self.coordinator.async_update_listeners()
