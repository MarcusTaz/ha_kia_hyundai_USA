"""Select entity for seats."""

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

OFF = ["Off"]
HEAT_OPTIONS = {
    3: ["High Heat", "Medium Heat", "Low Heat"],
    2: ["High Heat", "Low Heat"],
}
COOL_OPTIONS = {
    3: ["High Cool", "Medium Cool", "Low Cool"],
    2: ["High Cool", "Low Cool"],
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
        exists_fn=lambda coordinator: bool(coordinator.front_seat_options.get(HEAT_TYPE, 0)),
        value_fn=lambda coordinator: SEAT_STATUS.get(coordinator.climate_driver_seat, "Off"),
        options_fn=lambda coordinator: coordinator.front_seat_options,
    ),
    KiaSelectEntityDescription(
        key="desired_passenger_seat_comfort",
        name="Seat-Passenger with Climate",
        exists_fn=lambda coordinator: bool(coordinator.front_seat_options.get(HEAT_TYPE, 0)),
        value_fn=lambda coordinator: SEAT_STATUS.get(coordinator.climate_passenger_seat, "Off"),
        options_fn=lambda coordinator: coordinator.front_seat_options,
    ),
    KiaSelectEntityDescription(
        key="desired_left_rear_seat_comfort",
        name="Seat-Left Rear with Climate",
        exists_fn=lambda coordinator: bool(coordinator.rear_seat_options.get(HEAT_TYPE, 0)),
        value_fn=lambda coordinator: SEAT_STATUS.get(coordinator.climate_left_rear_seat, "Off"),
        options_fn=lambda coordinator: coordinator.rear_seat_options,
    ),
    KiaSelectEntityDescription(
        key="desired_right_rear_seat_comfort",
        name="Seat-Right Rear with Climate",
        exists_fn=lambda coordinator: bool(coordinator.rear_seat_options.get(HEAT_TYPE, 0)),
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

    entities = []
    for coordinator in coordinators.values():
        entities.extend(
            SeatSelect(coordinator, select_description)
            for select_description in SEAT_SELECTIONS
            if coordinator.has_climate_seats
            if select_description.exists_fn(coordinator)
        )
    
    async_add_entities(entities)


class SeatSelect(VehicleCoordinatorBaseEntity, SelectEntity, RestoreEntity):
    """Class for seat select entities."""

    entity_description: KiaSelectEntityDescription

    @property
    def options(self) -> list[str]:
        """Return the available options."""
        installed_options = self.entity_description.options_fn(self.coordinator)
        if installed_options:
            if installed_options[HEAT_TYPE] == 3:
                return (
                    OFF
                    + HEAT_OPTIONS[installed_options[STEPS]]
                    + COOL_OPTIONS[installed_options[STEPS]]
                )
            if installed_options[HEAT_TYPE] == 2:
                return OFF + COOL_OPTIONS[installed_options[STEPS]]
            return OFF + HEAT_OPTIONS[installed_options[STEPS]]
        return OFF

    @property
    def available(self) -> bool:
        """Return if the selector is available."""
        return super().available

    async def async_select_option(self, option: str) -> None:
        """Change the select option."""
        setattr(
            self.coordinator,
            self.entity_description.key,
            STR_TO_SEAT_SETTING[option],
        )
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
