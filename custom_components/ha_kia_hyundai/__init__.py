"""Kia/Hyundai US Integration using EU library for auth/API.

This integration uses the hyundai-kia-connect-api (EU library) for
authentication and API calls while maintaining the US integration's
sensor definitions and entity structure.
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

from .api_adapter import EUApiAdapter, create_vehicle_manager
from .const import (
    CONF_BRAND,
    CONF_PIN,
    DOMAIN,
    PLATFORMS,
    CONF_VEHICLE_ID,
    DEFAULT_SCAN_INTERVAL,
    CONFIG_FLOW_VERSION,
    BRAND_KIA,
)
from .services import async_setup_services, async_unload_services
from .vehicle_coordinator import VehicleCoordinator


_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.debug(
        "Migrating configuration from version %s.%s",
        config_entry.version,
        config_entry.minor_version
    )

    if config_entry.version > CONFIG_FLOW_VERSION:
        # This means the user has downgraded from a future version
        return False

    if config_entry.version == 2:
        _LOGGER.debug(f"Migrating from v2: {config_entry.data}")
        new_data = {
            CONF_USERNAME: config_entry.data[CONF_USERNAME],
            CONF_PASSWORD: config_entry.data[CONF_PASSWORD],
            CONF_VEHICLE_ID: config_entry.data["vehicle_identifier"],
            CONF_BRAND: config_entry.data.get(CONF_BRAND, BRAND_KIA),
            CONF_PIN: config_entry.data.get(CONF_PIN, ""),
        }
        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            minor_version=1,
            version=CONFIG_FLOW_VERSION
        )

    if config_entry.version == 3:
        _LOGGER.debug(f"Migrating from v3 to v4: {config_entry.data}")
        # Add brand and pin fields for EU library
        new_data = dict(config_entry.data)
        if CONF_BRAND not in new_data:
            new_data[CONF_BRAND] = BRAND_KIA
        if CONF_PIN not in new_data:
            new_data[CONF_PIN] = ""
        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            minor_version=1,
            version=CONFIG_FLOW_VERSION
        )

    _LOGGER.debug(
        "Migration to configuration version %s.%s successful",
        config_entry.version,
        config_entry.minor_version
    )

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up Kia/Hyundai US from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    async_setup_services(hass)

    vehicle_id = config_entry.data[CONF_VEHICLE_ID]
    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]
    brand = config_entry.data.get(CONF_BRAND, BRAND_KIA)
    pin = config_entry.data.get(CONF_PIN, "")

    scan_interval = timedelta(
        minutes=config_entry.options.get(
            CONF_SCAN_INTERVAL,
            DEFAULT_SCAN_INTERVAL,
        )
    )

    _LOGGER.info(
        "Setting up Kia/Hyundai US integration for vehicle %s",
        vehicle_id
    )

    try:
        # Create VehicleManager using EU library
        # No OTP handler during setup - auth should already be complete
        vehicle_manager = await create_vehicle_manager(
            username=username,
            password=password,
            brand=brand,
            pin=pin,
        )

        # Initialize and get vehicles
        _LOGGER.debug("Initializing VehicleManager")
        await vehicle_manager.check_and_refresh_token()
        await vehicle_manager.initialize()

        # Find our vehicle
        _LOGGER.debug("Looking for vehicle %s in manager.vehicles", vehicle_id)
        vehicle = None
        vehicle_name = None
        vehicle_model = None

        for vid, v in vehicle_manager.vehicles.items():
            _LOGGER.debug("Found vehicle: id=%s, name=%s, model=%s", vid, v.name, v.model)
            if vid == vehicle_id:
                vehicle = v
                vehicle_name = v.name
                vehicle_model = v.model
                break

        if vehicle is None:
            _LOGGER.error(
                "Vehicle %s not found. Available vehicles: %s",
                vehicle_id,
                list(vehicle_manager.vehicles.keys())
            )
            raise ConfigEntryError(f"Vehicle {vehicle_id} not found in account")

        # Create the API adapter
        api_adapter = EUApiAdapter(
            vehicle_manager=vehicle_manager,
            vehicle_id=vehicle_id,
        )

        # Create coordinator
        coordinator = VehicleCoordinator(
            hass=hass,
            config_entry=config_entry,
            vehicle_id=vehicle_id,
            vehicle_name=vehicle_name or vehicle_id,
            vehicle_model=vehicle_model or "Unknown",
            api_connection=api_adapter,
            scan_interval=scan_interval,
        )

        _LOGGER.debug("Starting first refresh for %s", vehicle_name)
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.debug("First refresh completed for %s", vehicle_name)

        hass.data[DOMAIN][vehicle_id] = coordinator

        await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

        if not config_entry.update_listeners:
            config_entry.add_update_listener(async_update_options)

        return True

    except ConfigEntryAuthFailed:
        raise
    except ConfigEntryError:
        raise
    except Exception as err:
        _LOGGER.exception("Error setting up Kia/Hyundai US integration: %s", err)
        raise ConfigEntryError(f"Failed to set up integration: {err}") from err


async def async_update_options(hass: HomeAssistant, config_entry: ConfigEntry):
    """Handle options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    ):
        vehicle_id = config_entry.unique_id
        coordinator = hass.data[DOMAIN].get(vehicle_id)
        if coordinator:
            # Close the API adapter (cleanup if needed)
            await coordinator.api_connection.close()
            del hass.data[DOMAIN][vehicle_id]

    if not hass.data[DOMAIN]:
        async_unload_services(hass)

    return unload_ok
