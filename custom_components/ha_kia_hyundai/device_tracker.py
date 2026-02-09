from logging import getLogger

from homeassistant.components.device_tracker import SourceType, TrackerEntityDescription
from homeassistant.components.device_tracker.config_entry import TrackerEntity
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
        entities.append(LocationTracker(coordinator))

    async_add_entities(entities)


class LocationTracker(VehicleCoordinatorBaseEntity, TrackerEntity):
    def __init__(self, coordinator: VehicleCoordinator):
        super().__init__(coordinator, TrackerEntityDescription(
            key="location",
            name="Location",
            icon="mdi:map-marker-outline",
        ))

    @property
    def source_type(self):
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return self.coordinator.latitude

    @property
    def longitude(self) -> float | None:
        return self.coordinator.longitude

    @property
    def available(self) -> bool:
        return super().available and self.latitude is not None and self.longitude is not None
