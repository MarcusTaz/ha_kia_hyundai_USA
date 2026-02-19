import logging

from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)

from . import VehicleCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class VehicleCoordinatorBaseEntity(CoordinatorEntity[VehicleCoordinator]):
    def __init__(self, coordinator: VehicleCoordinator, entity_description: EntityDescription):
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = f"{DOMAIN}-{coordinator.vehicle_id}-{self.entity_description.key}"
        self._attr_name = f"{coordinator.vehicle_name} {self.entity_description.name}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.coordinator.vehicle_id)},
            "name": self.coordinator.vehicle_name,
            "manufacturer": "US Kia",
            "model": self.coordinator.vehicle_model,
        }
