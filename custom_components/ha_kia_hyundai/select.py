"""Select entity for seats."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import VehicleCoordinator, get_all_coordinators
from .const import DOMAIN, SEAT_STATUS, STR_TO_SEAT_SETTING
from .vehicle_coordinator_base_entity import VehicleCoordinatorBaseEntity

_LOGGER = logging.getLogger(__name__)

OFF = ["Off"]
HEAT_OPTIONS = {
    3: ["High Heat", "Medium Heat", "Low Heat"],
    2: ["High Heat", "Low Heat"],
}
COOL_OPTIONS = {
    3: ["High Cool", "Medium Cool", "Low Cool"],
    2: ["High Cool", "Low Cool"],
}

# Steering wheel heat options based on step level
STEERING_WHEEL_OPTIONS = {
    1: ["Off", "On"],  # Single level
    2: ["Off", "Low", "High"],  # Two levels
}

# Map steering wheel option strings to API values
STEERING_WHEEL_STR_TO_VALUE = {
    "Off": 0,
    "On": 1,
    "Low": 1,
    "High": 2,
}

HEAT_TYPE = "heatVentType"
STEPS = "heatVentStep"


@dataclass(frozen=True, kw_only=True)
class KiaSelectEntityDescription(SelectEntityDescription):
    """Class for Kia select entities."""

    exists_fn: Callable[[VehicleCoordinator], bool] = lambda _: True
    value_fn: Callable[[VehicleCoordinator], str | None]
    options_fn: Callable[[VehicleCoordinator], dict[str, int] | None]
    icon = "mdi:car-seat"


SEAT_SELECTIONS: Final[tuple[KiaSelectEntityDescription, ...]] = (
    KiaSelectEntityDescription(
        key="desired_driver_seat_comfort",
        name="Seat-Driver with Climate",
        exists_fn=lambda coordinator: True,  # Existence checked by has_climate_seats
        value_fn=lambda coordinator: SEAT_STATUS.get(coordinator.climate_driver_seat, "Off"),
        options_fn=lambda coordinator: coordinator.front_seat_options,
    ),
    KiaSelectEntityDescription(
        key="desired_passenger_seat_comfort",
        name="Seat-Passenger with Climate",
        exists_fn=lambda coordinator: True,  # Existence checked by has_climate_seats
        value_fn=lambda coordinator: SEAT_STATUS.get(coordinator.climate_passenger_seat, "Off"),
        options_fn=lambda coordinator: coordinator.front_seat_options,
    ),
    KiaSelectEntityDescription(
        key="desired_left_rear_seat_comfort",
        name="Seat-Left Rear with Climate",
        exists_fn=lambda coordinator: bool(coordinator.rear_seat_options.get(HEAT_TYPE, 0)),  # Rear seats may not exist
        value_fn=lambda coordinator: SEAT_STATUS.get(coordinator.climate_left_rear_seat, "Off"),
        options_fn=lambda coordinator: coordinator.rear_seat_options,
    ),
    KiaSelectEntityDescription(
        key="desired_right_rear_seat_comfort",
        name="Seat-Right Rear with Climate",
        exists_fn=lambda coordinator: bool(coordinator.rear_seat_options.get(HEAT_TYPE, 0)),  # Rear seats may not exist
        value_fn=lambda coordinator: SEAT_STATUS.get(coordinator.climate_right_rear_seat, "Off"),
        options_fn=lambda coordinator: coordinator.rear_seat_options,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the entity."""
    coordinators = get_all_coordinators(hass)

    entities: list[SelectEntity] = []
    for coordinator in coordinators.values():
        # Add seat climate selects
        entities.extend(
            SeatSelect(coordinator, select_description)
            for select_description in SEAT_SELECTIONS
            if coordinator.has_climate_seats
            if select_description.exists_fn(coordinator)
        )
        
        # Add steering wheel heat select
        if coordinator.has_heated_steering_wheel:
            _LOGGER.debug("Adding steering wheel heat select for %s (step_level=%s)", 
                         coordinator.vehicle_name, coordinator.steering_wheel_heat_step_level)
            entities.append(SteeringWheelHeatSelect(coordinator))
    
    async_add_entities(entities)


class SeatSelect(VehicleCoordinatorBaseEntity, SelectEntity, RestoreEntity):
    """Class for seat select entities."""

    entity_description: KiaSelectEntityDescription

    @property
    def options(self) -> list[str]:
        """Return the available options."""
        installed_options = self.entity_description.options_fn(self.coordinator)
        heat_type = installed_options.get(HEAT_TYPE, 0) if installed_options else 0
        steps = installed_options.get(STEPS, 3) if installed_options else 3  # Default to 3 levels
        
        # If heat_type is 0 or unknown, default to showing all options (heat + cool with 3 levels)
        if heat_type == 3 or heat_type == 0:
            # Both heat and cool, or unknown - show all options
            return OFF + HEAT_OPTIONS.get(steps, HEAT_OPTIONS[3]) + COOL_OPTIONS.get(steps, COOL_OPTIONS[3])
        if heat_type == 2:
            # Cool only
            return OFF + COOL_OPTIONS.get(steps, COOL_OPTIONS[3])
        if heat_type == 1:
            # Heat only
            return OFF + HEAT_OPTIONS.get(steps, HEAT_OPTIONS[3])
        # Fallback - show all options
        return OFF + HEAT_OPTIONS[3] + COOL_OPTIONS[3]

    @property
    def available(self) -> bool:
        """Return if the selector is available."""
        return super().available

    async def async_select_option(self, option: str) -> None:
        """Change the select option."""
        _LOGGER.info(
            "SEAT SELECT: Setting %s to %s (SeatSettings=%s) on coordinator for %s",
            self.entity_description.key,
            option,
            STR_TO_SEAT_SETTING.get(option),
            self.coordinator.vehicle_name,
        )
        setattr(
            self.coordinator,
            self.entity_description.key,
            STR_TO_SEAT_SETTING[option],
        )
        # Verify it was set
        new_value = getattr(self.coordinator, self.entity_description.key, "NOT FOUND")
        _LOGGER.info("SEAT SELECT: Verified value is now: %s", new_value)
        self._attr_current_option = option
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state when added to Hass."""
        await super().async_added_to_hass()
        previous_state = await self.async_get_last_state()
        if previous_state is not None and previous_state.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            self._attr_current_option = previous_state.state
        else:
            self._attr_current_option = self.entity_description.value_fn(
                self.coordinator
            )

        setattr(
            self.coordinator,
            self.entity_description.key,
            STR_TO_SEAT_SETTING[self._attr_current_option or "Off"],
        )


class SteeringWheelHeatSelect(VehicleCoordinatorBaseEntity, SelectEntity, RestoreEntity):
    """Select entity for steering wheel heat."""

    def __init__(self, coordinator: VehicleCoordinator):
        """Initialize steering wheel heat select."""
        super().__init__(coordinator, SelectEntityDescription(
            key="desired_steering_wheel_heat",
            name="Steering Wheel Heat with Climate",
            icon="mdi:steering",
        ))

    @property
    def options(self) -> list[str]:
        """Return the available options based on step level."""
        step_level = self.coordinator.steering_wheel_heat_step_level
        return STEERING_WHEEL_OPTIONS.get(step_level, STEERING_WHEEL_OPTIONS[2])

    @property
    def current_option(self) -> str | None:
        """Return the current option."""
        return self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.info(
            "STEERING WHEEL: Setting to %s (value=%s) on coordinator for %s",
            option,
            STEERING_WHEEL_STR_TO_VALUE.get(option, 0),
            self.coordinator.vehicle_name,
        )
        self.coordinator.desired_steering_wheel_heat = STEERING_WHEEL_STR_TO_VALUE.get(option, 0)
        _LOGGER.info("STEERING WHEEL: Verified value is now: %s", self.coordinator.desired_steering_wheel_heat)
        self._attr_current_option = option
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous state when added to Hass."""
        await super().async_added_to_hass()
        previous_state = await self.async_get_last_state()
        if previous_state is not None and previous_state.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            self._attr_current_option = previous_state.state
        else:
            # Get current value from vehicle status
            current_step = self.coordinator.climate_steering_wheel_step
            if current_step == 0:
                self._attr_current_option = "Off"
            elif current_step == 1:
                step_level = self.coordinator.steering_wheel_heat_step_level
                self._attr_current_option = "Low" if step_level == 2 else "On"
            else:
                self._attr_current_option = "High"

        self.coordinator.desired_steering_wheel_heat = STEERING_WHEEL_STR_TO_VALUE.get(
            self._attr_current_option or "Off", 0
        )
