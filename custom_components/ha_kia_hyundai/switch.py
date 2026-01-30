from logging import getLogger

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import VehicleCoordinator, get_all_coordinators
from .const import DOMAIN
from .vehicle_coordinator_base_entity import VehicleCoordinatorBaseEntity

_LOGGER = getLogger(__name__)
PARALLEL_UPDATES: int = 1


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    coordinators = get_all_coordinators(hass)

    switches: list[SwitchEntity] = []
    for coordinator in coordinators.values():
        if coordinator.is_ev:
            switches.append(ChargingSwitch(coordinator=coordinator))
        
        if coordinator.can_remote_climate:
            _LOGGER.debug("Adding climate related switch entities for %s", coordinator.vehicle_name)
            switches.append(ClimateDesiredDefrostSwitch(coordinator=coordinator))
            switches.append(ClimateDesiredHeatingAccSwitch(coordinator=coordinator))
        else:
            _LOGGER.debug("Skipping climate related switch entities for %s", coordinator.vehicle_name)
    
    async_add_entities(switches)


class ClimateDesiredDefrostSwitch(VehicleCoordinatorBaseEntity, SwitchEntity, RestoreEntity):
    def __init__(
            self,
            coordinator: VehicleCoordinator,
    ):
        super().__init__(coordinator, SwitchEntityDescription(
            key="climate_desired_defrost",
            name="Front Defrost with Climate",
            icon="mdi:car-defrost-front",
            device_class=SwitchDeviceClass.SWITCH,
        ))

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.climate_desired_defrost

    async def async_turn_on(self, **kwargs: any) -> None:
        self.coordinator.climate_desired_defrost = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: any) -> None:
        self.coordinator.climate_desired_defrost = False
        self.async_write_ha_state()

    async def async_internal_added_to_hass(self) -> None:
        """Call when the button is added to hass."""
        await super().async_internal_added_to_hass()
        state = await self.async_get_last_state()
        if state is not None and state.state not in (STATE_UNAVAILABLE, None):
            self.__set_state(state.state)

    def __set_state(self, state: str | None) -> None:
        """Set the entity state."""
        # Invalidate the cache of the cached property
        self.__dict__.pop("state", None)
        self.coordinator.climate_desired_defrost = state == STATE_ON


class ClimateDesiredHeatingAccSwitch(VehicleCoordinatorBaseEntity, SwitchEntity, RestoreEntity):
    def __init__(
            self,
            coordinator: VehicleCoordinator
    ):
        super().__init__(coordinator, SwitchEntityDescription(
            key="climate_desired_heating_acc",
            name="Rear Defrost with Climate",
            icon="mdi:car-defrost-rear",
            device_class=SwitchDeviceClass.SWITCH,
        ))

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.climate_desired_heating_acc

    async def async_turn_on(self, **kwargs: any) -> None:
        self.coordinator.climate_desired_heating_acc = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: any) -> None:
        self.coordinator.climate_desired_heating_acc = False
        self.async_write_ha_state()

    async def async_internal_added_to_hass(self) -> None:
        """Call when the button is added to hass."""
        await super().async_internal_added_to_hass()
        state = await self.async_get_last_state()
        if state is not None and state.state not in (STATE_UNAVAILABLE, None):
            self.__set_state(state.state)

    def __set_state(self, state: str | None) -> None:
        """Set the entity state."""
        # Invalidate the cache of the cached property
        self.__dict__.pop("state", None)
        self.coordinator.climate_desired_heating_acc = state == STATE_ON

class ChargingSwitch(VehicleCoordinatorBaseEntity, SwitchEntity):
    def __init__(
            self,
            coordinator: VehicleCoordinator,
    ):
        super().__init__(coordinator, SwitchEntityDescription(
            key="ev_battery_charging",
            name="Charging",
            icon="mdi:ev-station",
            device_class=SwitchDeviceClass.SWITCH,
        ))

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.ev_plugged_in

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.ev_battery_charging

    async def async_turn_on(self, **kwargs: any) -> None:
        await self.coordinator.api_connection.start_charge(vehicle_id=self.coordinator.vehicle_id)
        self.coordinator.async_update_listeners()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: any) -> None:
        await self.coordinator.api_connection.stop_charge(vehicle_id=self.coordinator.vehicle_id)
        self.coordinator.async_update_listeners()
        await self.coordinator.async_request_refresh()
