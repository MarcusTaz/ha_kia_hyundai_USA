from logging import getLogger

from homeassistant.components.lock import LockEntity, LockEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import get_all_coordinators
from .vehicle_coordinator import VehicleCoordinator
from .vehicle_coordinator_base_entity import VehicleCoordinatorBaseEntity

_LOGGER = getLogger(__name__)
PARALLEL_UPDATES: int = 1


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    coordinators = get_all_coordinators(hass)

    entities = []
    for coordinator in coordinators.values():
        if coordinator.can_remote_lock:
            entities.append(Lock(coordinator))

    async_add_entities(entities)


class Lock(VehicleCoordinatorBaseEntity, LockEntity):
    def __init__(
        self,
        coordinator: VehicleCoordinator,
    ):
        super().__init__(coordinator, LockEntityDescription(
            key="doors_locked",
            name="Door Lock",
        ))

    @property
    def is_locked(self) -> bool:
        return self.coordinator.doors_locked

    @property
    def icon(self):
        return "mdi:lock" if self.is_locked else "mdi:lock-open-variant"

    async def async_lock(self, **kwargs: any):
        await self.coordinator.api_connection.lock(vehicle_id=self.coordinator.vehicle_id)
        self.coordinator.async_update_listeners()
        await self.coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs: any):
        await self.coordinator.api_connection.unlock(vehicle_id=self.coordinator.vehicle_id)
        self.coordinator.async_update_listeners()
        await self.coordinator.async_request_refresh()
