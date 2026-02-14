from dataclasses import dataclass, field
from logging import getLogger
from typing import TYPE_CHECKING, Final
from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription, \
    BinarySensorDeviceClass
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import VehicleCoordinator, get_all_coordinators
from .vehicle_coordinator_base_entity import VehicleCoordinatorBaseEntity

if TYPE_CHECKING:
    from .vehicle_coordinator import VehicleCoordinator

_LOGGER = getLogger(__name__)
PARALLEL_UPDATES: int = 1


@dataclass(frozen=True)
class KiaBinarySensorEntityDescription(BinarySensorEntityDescription):
    """A class that describes custom binary sensor entities."""
    on_icon: str | None = None
    off_icon: str | None = None
    exists_fn: Callable[["VehicleCoordinator"], bool] = field(default=lambda c: True)

BINARY_SENSOR_DESCRIPTIONS: Final[tuple[KiaBinarySensorEntityDescription, ...]] = (
    KiaBinarySensorEntityDescription(
        key="doors_locked",
        name="Locked",
        icon="mdi:lock",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    KiaBinarySensorEntityDescription(
        key="door_hood_open",
        name="Hood",
        icon="mdi:car",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    KiaBinarySensorEntityDescription(
        key="door_trunk_open",
        name="Trunk",
        on_icon="mdi:car-back",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    KiaBinarySensorEntityDescription(
        key="door_front_left_open",
        name="Door - Front Left",
        icon="mdi:car-door",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    KiaBinarySensorEntityDescription(
        key="door_front_right_open",
        name="Door - Front Right",
        icon="mdi:car-door",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    KiaBinarySensorEntityDescription(
        key="door_back_left_open",
        name="Door - Rear Left",
        icon="mdi:car-door",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    KiaBinarySensorEntityDescription(
        key="door_back_right_open",
        name="Door - Rear Right",
        icon="mdi:car-door",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    KiaBinarySensorEntityDescription(
        key="engine_on",
        name="Engine",
        on_icon="mdi:engine",
        off_icon="mdi:engine-off",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    KiaBinarySensorEntityDescription(
        key="tire_all_on",
        name="Tire Pressure - All",
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:tire",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    KiaBinarySensorEntityDescription(
        key="climate_hvac_on",
        name="HVAC",
        icon="mdi:air-conditioner",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    KiaBinarySensorEntityDescription(
        key="climate_defrost_on",
        name="Defroster",
        icon="mdi:car-defrost-front",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    KiaBinarySensorEntityDescription(
        key="climate_heated_rear_window_on",
        name="Rear Window Heater",
        icon="mdi:car-defrost-rear",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    KiaBinarySensorEntityDescription(
        key="climate_heated_side_mirror_on",
        name="Side Mirror Heater",
        icon="mdi:car-side",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    KiaBinarySensorEntityDescription(
        key="climate_heated_steering_wheel_on",
        name="Steering Wheel Heater",
        icon="mdi:steering",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    KiaBinarySensorEntityDescription(
        key="low_fuel_light_on",
        name="Low Fuel Light",
        on_icon="mdi:gas-station-off",
        off_icon="mdi:gas-station",
        device_class=BinarySensorDeviceClass.PROBLEM,
        exists_fn=lambda c: not c.is_ev,  # Only show for ICE/hybrid vehicles
    ),
    KiaBinarySensorEntityDescription(
        key="ev_battery_charging",
        name="Charging",
        on_icon="mdi:battery-charging",
        off_icon="mdi:battery",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    ),
    KiaBinarySensorEntityDescription(
        key="ev_plugged_in",
        name="Plugged In",
        on_icon="mdi:power-plug",
        off_icon="mdi:power-plug-off",
        device_class=BinarySensorDeviceClass.PLUG,
    ),
    KiaBinarySensorEntityDescription(
        key="ev_battery_preconditioning",
        name="Battery Preconditioning",
        on_icon="mdi:battery-heart",
        off_icon="mdi:battery-heart-outline",
        device_class=BinarySensorDeviceClass.RUNNING,
        exists_fn=lambda c: c.is_ev,  # Only show for EVs
    ),
)

async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    coordinators = get_all_coordinators(hass)

    binary_sensors = []
    for coordinator in coordinators.values():
        for description in BINARY_SENSOR_DESCRIPTIONS:
            if not description.exists_fn(coordinator):
                _LOGGER.debug("Skipping binary sensor %s - exists_fn returned False", description.key)
                continue
            if getattr(coordinator, description.key) is not None:
                binary_sensors.append(
                    InstrumentSensor(
                        coordinator=coordinator,
                        description=description,
                    )
                )
    async_add_entities(binary_sensors)


class InstrumentSensor(VehicleCoordinatorBaseEntity, BinarySensorEntity, RestoreEntity):
    """Binary sensor that preserves last known state when vehicle sleeps."""

    def __init__(
            self,
            coordinator: VehicleCoordinator,
            description: KiaBinarySensorEntityDescription,
    ):
        super().__init__(coordinator, description)
        self._attr_is_on: bool | None = None

    @property
    def icon(self):
        if self.entity_description.icon is not None:
            return self.entity_description.icon
        return self.entity_description.on_icon if self.is_on else self.entity_description.off_icon

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on, preserving last state if unavailable."""
        value = getattr(self.coordinator, self.entity_description.key)
        if value is not None:
            # Invert for doors_locked (locked = not open)
            if self.entity_description.key == "doors_locked":
                self._attr_is_on = not value
            else:
                self._attr_is_on = value
        return self._attr_is_on

    @property
    def available(self) -> bool:
        """Return True if we have a value (current or preserved)."""
        return super().available and self.is_on is not None

    async def async_added_to_hass(self) -> None:
        """Restore last known state when added to hass."""
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state is not None and state.state not in (STATE_UNAVAILABLE, None, "unknown"):
            self._attr_is_on = state.state == "on"
            _LOGGER.debug("Restored %s state to %s", self.entity_description.key, self._attr_is_on)
