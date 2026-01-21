"""Kia/Hyundai US integration using fixed kia-hyundai-api.

This integration uses an embedded, fixed version of kia-hyundai-api with:
- Updated API headers matching the current Kia iOS app
- Fixed OTP flow with proper _complete_login_with_otp step
- Added tncFlag to login payload
"""

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SCAN_INTERVAL,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

# Use embedded fixed library
from .kia_hyundai_api import UsKia, AuthError

from .const import (
    CONF_DEVICE_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    PLATFORMS,
    CONF_VEHICLE_ID,
    DEFAULT_SCAN_INTERVAL,
    CONFIG_FLOW_VERSION,
)
from .services import async_setup_services, async_unload_services
from .vehicle_coordinator import VehicleCoordinator


_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.debug("Migrating configuration from version %s.%s", config_entry.version, config_entry.minor_version)

    if config_entry.version > CONFIG_FLOW_VERSION:
        return False

    if config_entry.version < 3:
        # Migration from old versions to v3
        new_data = {**config_entry.data}
        # Remove old OTP fields if present
        for key in ["otp_type", "otp_code", "access_token"]:
            new_data.pop(key, None)
        
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, version=3
        )
        _LOGGER.info("Migration to version 3 successful")

    if config_entry.version < 5:
        # Migration to v5 - ensure required fields exist
        new_data = {**config_entry.data}
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, version=5
        )
        _LOGGER.info("Migration to version 5 successful")

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up Kia/Hyundai US from a config entry."""
    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]
    vehicle_id = config_entry.data[CONF_VEHICLE_ID]
    device_id = config_entry.data.get(CONF_DEVICE_ID)
    refresh_token = config_entry.data.get(CONF_REFRESH_TOKEN)

    scan_interval = timedelta(
        minutes=config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )

    _LOGGER.info("Setting up Kia/Hyundai US integration for vehicle %s", vehicle_id)

    try:
        client_session = async_get_clientsession(hass)
        
        # Dummy OTP callback - should not be called during normal operation
        # since we have a valid refresh_token from config_flow
        async def otp_callback(context):
            _LOGGER.error("OTP callback called unexpectedly during entry setup")
            raise ConfigEntryAuthFailed("OTP required - please reconfigure the integration")

        # Create API connection with stored credentials
        api_connection = UsKia(
            username=username,
            password=password,
            otp_callback=otp_callback,
            device_id=device_id,
            refresh_token=refresh_token,
            client_session=client_session,
        )

        _LOGGER.debug("Logging in to Kia API...")
        await api_connection.login()
        _LOGGER.debug("Login successful, session_id: %s", api_connection.session_id is not None)

        # Get vehicles to find the one we want
        await api_connection.get_vehicles()
        
        if api_connection.vehicles is None:
            raise ConfigEntryError("No vehicles found in account")

        # Find our vehicle
        vehicle = None
        vehicle_name = "Unknown"
        vehicle_model = "Unknown"
        for v in api_connection.vehicles:
            if v["vehicleIdentifier"] == vehicle_id:
                vehicle = v
                vehicle_name = v.get("nickName", "Unknown")
                vehicle_model = v.get("modelName", "Unknown")
                break

        if vehicle is None:
            raise ConfigEntryError(f"Vehicle {vehicle_id} not found in account")

        _LOGGER.info("Found vehicle: %s (%s)", vehicle_name, vehicle_model)

        # Update stored tokens if they changed
        new_data = {**config_entry.data}
        if api_connection.device_id != device_id:
            new_data[CONF_DEVICE_ID] = api_connection.device_id
        if api_connection.refresh_token != refresh_token:
            new_data[CONF_REFRESH_TOKEN] = api_connection.refresh_token
        
        if new_data != config_entry.data:
            hass.config_entries.async_update_entry(config_entry, data=new_data)

        # Create the coordinator
        coordinator = VehicleCoordinator(
            hass=hass,
            config_entry=config_entry,
            vehicle_id=vehicle_id,
            vehicle_name=vehicle_name,
            vehicle_model=vehicle_model,
            api_connection=api_connection,
            scan_interval=scan_interval,
        )

        # Do first refresh
        _LOGGER.debug("Starting first data refresh for %s", vehicle_name)
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.debug("First refresh completed for %s", vehicle_name)

        # Store coordinator
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][vehicle_id] = coordinator

        # Set up platforms
        await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

        # Set up services
        await async_setup_services(hass)

        return True

    except AuthError as err:
        _LOGGER.error("Authentication failed: %s", err)
        raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
    except Exception as err:
        _LOGGER.exception("Error setting up integration: %s", err)
        raise ConfigEntryError(f"Error setting up integration: {err}") from err


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    vehicle_id = config_entry.data[CONF_VEHICLE_ID]
    
    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(vehicle_id, None)
        
        # Unload services if no more entries
        if not hass.data[DOMAIN]:
            await async_unload_services(hass)
            hass.data.pop(DOMAIN, None)

    return unload_ok
