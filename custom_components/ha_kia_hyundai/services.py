from logging import getLogger
from typing import cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import device_registry

from .const import DOMAIN, STR_TO_SEAT_SETTING
from .vehicle_coordinator import VehicleCoordinator

# Key for coordinators in hass.data
COORDINATORS_KEY = "_coordinators"

SERVICE_START_CLIMATE = "start_climate"
SERVICE_SET_CHARGE_LIMIT = "set_charge_limits"

SERVICE_ATTRIBUTE_CLIMATE = "climate"
SERVICE_ATTRIBUTE_TEMPERATURE = "temperature"
SERVICE_ATTRIBUTE_DEFROST = "defrost"
SERVICE_ATTRIBUTE_HEATING = "heating"
SERVICE_ATTRIBUTE_DURATION = "duration"
SERVICE_ATTRIBUTE_DRIVER_SEAT = "driver_seat"
SERVICE_ATTRIBUTE_PASSENGER_SEAT = "passenger_seat"
SERVICE_ATTRIBUTE_LEFT_REAR_SEAT = "left_rear_seat"
SERVICE_ATTRIBUTE_RIGHT_REAR_SEAT = "right_rear_seat"

SUPPORTED_SERVICES = (
    SERVICE_START_CLIMATE,
    SERVICE_SET_CHARGE_LIMIT,
)

_LOGGER = getLogger(__name__)


def async_setup_services(hass: HomeAssistant):
    async def async_handle_start_climate(call: ServiceCall):
        coordinator: VehicleCoordinator = _get_coordinator_from_device(hass, call)
        climate = call.data.get(SERVICE_ATTRIBUTE_CLIMATE)
        set_temp = call.data.get(SERVICE_ATTRIBUTE_TEMPERATURE)
        defrost = call.data.get(SERVICE_ATTRIBUTE_DEFROST)
        heating = call.data.get(SERVICE_ATTRIBUTE_HEATING)
        duration = call.data.get(SERVICE_ATTRIBUTE_DURATION)
        driver_seat = call.data.get(SERVICE_ATTRIBUTE_DRIVER_SEAT, None)
        passenger_seat = call.data.get(SERVICE_ATTRIBUTE_PASSENGER_SEAT, None)
        left_rear_seat = call.data.get(SERVICE_ATTRIBUTE_LEFT_REAR_SEAT, None)
        right_rear_seat = call.data.get(SERVICE_ATTRIBUTE_RIGHT_REAR_SEAT, None)

        if set_temp is not None:
            set_temp = int(set_temp)
        if duration is not None:
            duration = int(duration)
        if driver_seat is not None:
            driver_seat = STR_TO_SEAT_SETTING[driver_seat]
        if passenger_seat is not None:
            passenger_seat = STR_TO_SEAT_SETTING[passenger_seat]
        if left_rear_seat is not None:
            left_rear_seat = STR_TO_SEAT_SETTING[left_rear_seat]
        if right_rear_seat is not None:
            right_rear_seat = STR_TO_SEAT_SETTING[right_rear_seat]

        # Build kwargs, only include duration if specified (otherwise API defaults to 10)
        kwargs = {
            "vehicle_id": coordinator.vehicle_id,
            "climate": bool(climate),
            "set_temp": set_temp,
            "defrost": bool(defrost),
            "heating": bool(heating),
            "driver_seat": driver_seat,
            "passenger_seat": passenger_seat,
            "left_rear_seat": left_rear_seat,
            "right_rear_seat": right_rear_seat,
        }
        if duration is not None:
            kwargs["duration"] = duration

        await coordinator.api_connection.start_climate(**kwargs)
        coordinator.async_update_listeners()
        await coordinator.async_request_refresh()

    async def async_handle_set_charge_limit(call: ServiceCall):
        coordinator: VehicleCoordinator = _get_coordinator_from_device(hass, call)
        ac_limit = int(call.data.get("ac_limit"))
        dc_limit = int(call.data.get("dc_limit"))

        await coordinator.api_connection.set_charge_limits(
            vehicle_id=coordinator.vehicle_id,
            ac_limit=ac_limit,
            dc_limit=dc_limit
        )
        coordinator.async_update_listeners()
        await coordinator.async_request_refresh()

    services = {
        SERVICE_START_CLIMATE: async_handle_start_climate,
        SERVICE_SET_CHARGE_LIMIT: async_handle_set_charge_limit,
    }
    for service in SUPPORTED_SERVICES:
        hass.services.async_register(DOMAIN, service, services[service])

    return True

def _get_coordinator_from_device(
        hass: HomeAssistant, call: ServiceCall
) -> VehicleCoordinator:
    coordinators = hass.data.get(DOMAIN, {}).get(COORDINATORS_KEY, {})
    
    # If only one vehicle, use it
    if len(coordinators) == 1:
        return list(coordinators.values())[0]
    
    # Otherwise, look up by device_id
    device_entry = device_registry.async_get(hass).async_get(
        call.data[ATTR_DEVICE_ID]
    )
    
    if device_entry is None:
        raise ValueError("Device not found")
    
    # The device identifiers contain (DOMAIN, vehicle_id)
    for identifier in device_entry.identifiers:
        if identifier[0] == DOMAIN:
            vehicle_id = identifier[1]
            if vehicle_id in coordinators:
                return coordinators[vehicle_id]
    
    raise ValueError(f"No coordinator found for device {call.data[ATTR_DEVICE_ID]}")

@callback
def async_unload_services(hass) -> None:
    for service in SUPPORTED_SERVICES:
        hass.services.async_remove(DOMAIN, service)
