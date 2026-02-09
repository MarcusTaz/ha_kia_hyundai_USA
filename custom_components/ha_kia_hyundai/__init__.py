"""Kia/Hyundai/Genesis US integration.

Architecture:
- ONE config entry per account (username + brand as unique_id)
- Multiple vehicles stored in the entry's data
- Each vehicle becomes a separate device in Home Assistant
- All vehicles share a single API connection to prevent session conflicts

Supported brands:
- Kia: Uses OTP-based authentication
- Hyundai: Uses PIN-based authentication (BlueLink)
- Genesis: Uses PIN-based authentication (Connected Services)
"""

import asyncio
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

# Use embedded API libraries
from .kia_hyundai_api import UsKia, AuthError
from .kia_hyundai_api.us_hyundai import UsHyundai
from .kia_hyundai_api.us_genesis import UsGenesis

from .const import (
    CONF_BRAND,
    CONF_DEVICE_ID,
    CONF_PIN,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    PLATFORMS,
    CONF_VEHICLE_ID,
    CONF_VEHICLES,
    DEFAULT_SCAN_INTERVAL,
    CONFIG_FLOW_VERSION,
    BRAND_KIA,
    BRAND_HYUNDAI,
    BRAND_GENESIS,
    BRANDS,
)
from .services import async_setup_services, async_unload_services
from .vehicle_coordinator import VehicleCoordinator


_LOGGER = logging.getLogger(__name__)

# Keys for hass.data storage
API_CONNECTION_KEY = "_api_connection"
API_CONNECTION_LOCK_KEY = "_api_lock"
COORDINATORS_KEY = "_coordinators"


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Migrate old entry format to new format."""
    _LOGGER.debug("Migrating configuration from version %s.%s", config_entry.version, config_entry.minor_version)

    if config_entry.version > CONFIG_FLOW_VERSION:
        return False

    # Handle legacy per-vehicle entries (version < 5 or has CONF_VEHICLE_ID but no CONF_VEHICLES)
    if CONF_VEHICLE_ID in config_entry.data and CONF_VEHICLES not in config_entry.data:
        _LOGGER.info("Migrating legacy per-vehicle entry to new format")

        # This is a legacy entry - we'll convert it to new format
        # The new format stores all vehicles, but since we only have one here,
        # we'll create a vehicles list with just this one
        new_data = {**config_entry.data}

        # Create vehicles list from the single vehicle_id
        vehicle_id = new_data.pop(CONF_VEHICLE_ID, None)
        if vehicle_id:
            new_data[CONF_VEHICLES] = [{
                "id": vehicle_id,
                "name": config_entry.title.split(" (")[0] if " (" in config_entry.title else config_entry.title,
                "model": "Unknown",
                "year": "",
                "vin": "",
                "key": "",
            }]
        else:
            new_data[CONF_VEHICLES] = []

        # Add brand if missing (legacy entries are all Kia)
        if CONF_BRAND not in new_data:
            new_data[CONF_BRAND] = BRAND_KIA

        # Remove old OTP fields if present
        for key in ["otp_type", "otp_code", "access_token"]:
            new_data.pop(key, None)

        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            version=CONFIG_FLOW_VERSION,
            title=config_entry.data.get(CONF_USERNAME, config_entry.title),
        )
        _LOGGER.info("Migration to version %s successful", CONFIG_FLOW_VERSION)

    elif config_entry.version < CONFIG_FLOW_VERSION:
        # Version bump without structural changes
        new_data = {**config_entry.data}

        # Add brand if missing (legacy entries are all Kia)
        if CONF_BRAND not in new_data:
            new_data[CONF_BRAND] = BRAND_KIA

        hass.config_entries.async_update_entry(
            config_entry, data=new_data, version=CONFIG_FLOW_VERSION
        )
        _LOGGER.info("Migration to version %s successful", CONFIG_FLOW_VERSION)

    return True


async def _get_or_create_api_connection(
    hass: HomeAssistant,
    brand: str,
    username: str,
    password: str,
    device_id: str | None,
    refresh_token: str | None = None,
    pin: str | None = None,
) -> UsKia | UsHyundai | UsGenesis:
    """Get or create a shared API connection for all vehicles.

    This prevents session conflicts when multiple vehicles are set up
    simultaneously with the same account.
    """
    hass.data.setdefault(DOMAIN, {})

    # Use brand-specific key for connection storage
    connection_key = f"{API_CONNECTION_KEY}_{brand}_{username}"
    lock_key = f"{API_CONNECTION_LOCK_KEY}_{brand}_{username}"

    # Create lock if it doesn't exist
    if lock_key not in hass.data[DOMAIN]:
        hass.data[DOMAIN][lock_key] = asyncio.Lock()

    lock = hass.data[DOMAIN][lock_key]

    async with lock:
        # Check if we already have a valid connection
        existing_connection = hass.data[DOMAIN].get(connection_key)
        if existing_connection is not None:
            # Verify the connection is still valid based on brand
            if brand == BRAND_KIA:
                if existing_connection.session_id is not None:
                    _LOGGER.debug("Reusing existing Kia API connection")
                    return existing_connection
            else:  # Hyundai or Genesis
                if existing_connection.access_token is not None:
                    _LOGGER.debug("Reusing existing %s API connection", BRANDS.get(brand, brand))
                    return existing_connection

            _LOGGER.debug("Existing connection has no session/token, creating new one")

        brand_name = BRANDS.get(brand, brand)
        _LOGGER.info("Creating new shared %s API connection", brand_name)

        client_session = async_get_clientsession(hass)

        if brand == BRAND_KIA:
            # Dummy OTP callback - should not be called during normal operation
            async def otp_callback(context):
                _LOGGER.error("OTP callback called unexpectedly during entry setup")
                raise ConfigEntryAuthFailed("OTP required - please reconfigure the integration")

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

        elif brand == BRAND_HYUNDAI:
            if not pin:
                raise ConfigEntryError("PIN required for Hyundai BlueLink")

            api_connection = UsHyundai(
                username=username,
                password=password,
                pin=pin,
                device_id=device_id,
                client_session=client_session,
            )

            _LOGGER.debug("Logging in to Hyundai BlueLink API...")
            await api_connection.login()
            _LOGGER.debug("Login successful, access_token: %s", api_connection.access_token is not None)

        elif brand == BRAND_GENESIS:
            if not pin:
                raise ConfigEntryError("PIN required for Genesis Connected Services")

            api_connection = UsGenesis(
                username=username,
                password=password,
                pin=pin,
                device_id=device_id,
                client_session=client_session,
            )

            _LOGGER.debug("Logging in to Genesis API...")
            await api_connection.login()
            _LOGGER.debug("Login successful, access_token: %s", api_connection.access_token is not None)

        else:
            raise ConfigEntryError(f"Unknown brand: {brand}")

        # Get vehicles from API to update local data
        await api_connection.get_vehicles()

        # Store the connection for reuse
        hass.data[DOMAIN][connection_key] = api_connection

        return api_connection


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up Kia/Hyundai/Genesis US from a config entry.

    This creates coordinators for ALL vehicles in the account.
    """
    # Get brand with fallback for legacy entries
    brand = config_entry.data.get(CONF_BRAND, BRAND_KIA)
    brand_name = BRANDS.get(brand, brand)

    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]
    device_id = config_entry.data.get(CONF_DEVICE_ID)
    refresh_token = config_entry.data.get(CONF_REFRESH_TOKEN)
    pin = config_entry.data.get(CONF_PIN)
    vehicles_config = config_entry.data.get(CONF_VEHICLES, [])

    scan_interval = timedelta(
        minutes=config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )

    _LOGGER.info("Setting up %s integration for account %s with %d vehicles",
                 brand_name, username, len(vehicles_config))

    hass.data.setdefault(DOMAIN, {})

    try:
        # Get or create shared API connection
        api_connection = await _get_or_create_api_connection(
            hass=hass,
            brand=brand,
            username=username,
            password=password,
            device_id=device_id,
            refresh_token=refresh_token,
            pin=pin,
        )

        if api_connection.vehicles is None:
            raise ConfigEntryError("No vehicles found in account")

        # Update stored tokens if they changed
        new_data = {**config_entry.data}
        data_changed = False

        if api_connection.device_id != device_id:
            new_data[CONF_DEVICE_ID] = api_connection.device_id
            data_changed = True

        # Only update refresh_token for Kia (Hyundai/Genesis don't use it the same way)
        if brand == BRAND_KIA:
            if hasattr(api_connection, 'refresh_token') and api_connection.refresh_token != refresh_token:
                new_data[CONF_REFRESH_TOKEN] = api_connection.refresh_token
                data_changed = True

        # Update vehicle info from API (vehicle keys/regids change on each login)
        updated_vehicles = []
        for api_vehicle in api_connection.vehicles:
            # Handle different field names by brand
            api_vehicle_id = api_vehicle.get("vehicleIdentifier", api_vehicle.get("id", api_vehicle.get("regid", "")))

            # Check if this vehicle is in our config
            for config_vehicle in vehicles_config:
                if config_vehicle.get("id") == api_vehicle_id:
                    # Update with latest info from API
                    updated_vehicles.append({
                        "id": api_vehicle_id,
                        "name": api_vehicle.get("nickName", config_vehicle.get("name", "Unknown")),
                        "model": api_vehicle.get("modelName", api_vehicle.get("modelCode", config_vehicle.get("model", "Unknown"))),
                        "year": api_vehicle.get("modelYear", config_vehicle.get("year", "")),
                        "vin": api_vehicle.get("vin", api_vehicle.get("VIN", config_vehicle.get("vin", ""))),
                        "key": api_vehicle.get("vehicleKey", api_vehicle.get("regid", config_vehicle.get("key", ""))),
                    })
                    break
            else:
                # Vehicle in API but not in config - add it
                _LOGGER.info("Found new vehicle in account: %s", api_vehicle.get("nickName", "Unknown"))
                updated_vehicles.append({
                    "id": api_vehicle_id,
                    "name": api_vehicle.get("nickName", "Unknown"),
                    "model": api_vehicle.get("modelName", api_vehicle.get("modelCode", "Unknown")),
                    "year": api_vehicle.get("modelYear", ""),
                    "vin": api_vehicle.get("vin", api_vehicle.get("VIN", "")),
                    "key": api_vehicle.get("vehicleKey", api_vehicle.get("regid", "")),
                })

        if updated_vehicles != vehicles_config:
            new_data[CONF_VEHICLES] = updated_vehicles
            vehicles_config = updated_vehicles
            data_changed = True

        if data_changed:
            hass.config_entries.async_update_entry(config_entry, data=new_data)

        # Create coordinators for all vehicles
        coordinators: dict[str, VehicleCoordinator] = {}

        for vehicle_info in vehicles_config:
            vehicle_id = vehicle_info.get("id")
            vehicle_name = vehicle_info.get("name", "Unknown")
            vehicle_model = vehicle_info.get("model", "Unknown")

            if not vehicle_id:
                _LOGGER.warning("Skipping vehicle with no ID: %s", vehicle_info)
                continue

            _LOGGER.info("Setting up vehicle: %s (%s)", vehicle_name, vehicle_model)

            # Create the coordinator for this vehicle
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
            try:
                await coordinator.async_config_entry_first_refresh()
                _LOGGER.debug("First refresh completed for %s", vehicle_name)
            except Exception as e:
                _LOGGER.error("Error during first refresh for %s: %s", vehicle_name, e)
                # Continue with other vehicles even if one fails
                continue

            coordinators[vehicle_id] = coordinator

        if not coordinators:
            raise ConfigEntryError("No vehicles could be set up")

        # Store coordinators
        hass.data[DOMAIN][COORDINATORS_KEY] = coordinators

        # Set up platforms
        await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

        # Set up services (not async, don't await)
        async_setup_services(hass)

        return True

    except AuthError as err:
        _LOGGER.error("Authentication failed: %s", err)
        raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
    except Exception as err:
        _LOGGER.exception("Error setting up integration: %s", err)
        raise ConfigEntryError(f"Error setting up integration: {err}") from err


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)

    if unload_ok:
        # Clean up coordinators
        hass.data[DOMAIN].pop(COORDINATORS_KEY, None)

        # Clean up shared API connection
        hass.data[DOMAIN].pop(API_CONNECTION_KEY, None)
        hass.data[DOMAIN].pop(API_CONNECTION_LOCK_KEY, None)

        # Unload services
        async_unload_services(hass)

        # Clean up domain data if empty
        if not any(k for k in hass.data[DOMAIN] if not k.startswith("_")):
            hass.data.pop(DOMAIN, None)

    return unload_ok


def get_coordinator(hass: HomeAssistant, vehicle_id: str) -> VehicleCoordinator | None:
    """Get coordinator for a specific vehicle."""
    coordinators = hass.data.get(DOMAIN, {}).get(COORDINATORS_KEY, {})
    return coordinators.get(vehicle_id)


def get_all_coordinators(hass: HomeAssistant) -> dict[str, VehicleCoordinator]:
    """Get all coordinators."""
    return hass.data.get(DOMAIN, {}).get(COORDINATORS_KEY, {})
