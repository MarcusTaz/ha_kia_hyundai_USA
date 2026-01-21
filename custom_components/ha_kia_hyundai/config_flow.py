"""Config flow for Kia/Hyundai US integration using fixed library.

The OTP flow:
1. User enters credentials and selects OTP delivery method (EMAIL/SMS)
2. Login is initiated, OTP is sent to chosen destination
3. User enters OTP code
4. Login completes and vehicles are discovered
5. All vehicles are automatically added
"""

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry, OptionsFlow
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant import config_entries
from homeassistant.const import (
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

# Use embedded fixed library
from .kia_hyundai_api import UsKia, AuthError

from .const import (
    CONF_DEVICE_ID,
    CONF_OTP_CODE,
    CONF_OTP_TYPE,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    CONFIG_FLOW_VERSION,
    CONF_VEHICLE_ID,
    DEFAULT_SCAN_INTERVAL,
    CONFIG_FLOW_TEMP_VEHICLES,
)

_LOGGER = logging.getLogger(__name__)


class KiaUvoOptionFlowHandler(OptionsFlow):
    """Handle options flow for Kia/Hyundai US."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=config_entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=999)),
            }
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Handle options flow."""
        if user_input is not None:
            _LOGGER.debug("User input in option flow: %s", user_input)
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(step_id="init", data_schema=self.schema)


@config_entries.HANDLERS.register(DOMAIN)
class KiaUvoConfigFlowHandler(config_entries.ConfigFlow):
    """Handle config flow for Kia/Hyundai US."""

    VERSION = CONFIG_FLOW_VERSION
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        """Initialize config flow."""
        self.data: dict[str, Any] = {}
        self.api_connection: UsKia | None = None
        self.otp_task = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get options flow handler."""
        return KiaUvoOptionFlowHandler(config_entry)

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None):
        """Handle re-authentication.
        
        When reauth is triggered, we get the existing config entry data as user_input,
        but it doesn't contain otp_type (which is only used during initial setup).
        We need to show the user form to get fresh credentials.
        """
        _LOGGER.debug("Reauth triggered, showing user form")
        # Store the existing entry data for reference (e.g., username)
        if user_input is not None:
            # Pre-populate the username from existing config
            self.data[CONF_USERNAME] = user_input.get(CONF_USERNAME, "")
        # Show the user form without passing the incomplete data
        return await self.async_step_user(None)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle user step - credentials input."""
        _LOGGER.debug("User step with input: %s", user_input)

        # Get default username from stored data (e.g., from reauth)
        default_username = self.data.get(CONF_USERNAME, "")
        
        data_schema = vol.Schema({
            vol.Required(CONF_USERNAME, default=default_username): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_OTP_TYPE, default="SMS"): vol.In(["EMAIL", "SMS"]),
        })
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            otp_type = user_input[CONF_OTP_TYPE]

            # OTP callback that handles the two-stage flow
            async def otp_callback(context: dict[str, Any]):
                stage = context.get("stage")
                _LOGGER.info("OTP callback called with stage: %s", stage)
                
                if stage == "choose_destination":
                    _LOGGER.info("OTP destination: %s (email available: %s, phone available: %s)",
                                otp_type, context.get("hasEmail"), context.get("hasPhone"))
                    return {"notify_type": otp_type}
                
                if stage == "input_code":
                    _LOGGER.info("Waiting for OTP code input...")
                    # Wait for user to enter OTP code (up to 2 minutes)
                    for i in range(120):
                        if CONF_OTP_CODE in self.data:
                            otp_code = self.data[CONF_OTP_CODE]
                            _LOGGER.info("OTP code received (length: %d)", len(otp_code))
                            return {"otp_code": otp_code}
                        await asyncio.sleep(1)
                    
                    raise ConfigEntryAuthFailed("2 minute timeout waiting for OTP code")
                
                raise ConfigEntryAuthFailed(f"Unknown OTP stage: {stage}")

            try:
                client_session = async_get_clientsession(self.hass)
                
                _LOGGER.info("Creating UsKia connection for %s", username)
                self.api_connection = UsKia(
                    username=username,
                    password=password,
                    otp_callback=otp_callback,
                    client_session=client_session,
                )
                _LOGGER.info("UsKia created with device_id: %s", self.api_connection.device_id)

                # Store user input
                self.data = {
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                    CONF_OTP_TYPE: otp_type,
                }

                # Start login task (runs in background while waiting for OTP)
                _LOGGER.info("Starting login task...")
                self.otp_task = self.hass.loop.create_task(self.api_connection.login())
                
                # Move to OTP code entry step
                return await self.async_step_otp_code()

            except AuthError as e:
                _LOGGER.error("Authentication error: %s", e)
                errors["base"] = "auth"
            except Exception as e:
                _LOGGER.exception("Error during login setup: %s", e)
                errors["base"] = "auth"

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_otp_code(self, user_input: dict[str, Any] | None = None):
        """Handle OTP code input step."""
        _LOGGER.debug("OTP code step with input: %s", user_input)

        data_schema = vol.Schema({
            vol.Required(CONF_OTP_CODE): str,
        })
        errors: dict[str, str] = {}

        if user_input is not None:
            # Store the OTP code so the callback can read it
            self.data[CONF_OTP_CODE] = user_input[CONF_OTP_CODE].strip()
            _LOGGER.info("OTP code stored, waiting for login to complete...")

            try:
                # Wait for login task to complete
                await self.otp_task
                _LOGGER.info("Login completed successfully!")

                if self.api_connection is None:
                    raise ConfigEntryAuthFailed("API connection not established")

                # Get vehicles
                _LOGGER.info("Getting vehicles...")
                await self.api_connection.get_vehicles()
                
                if not self.api_connection.vehicles:
                    _LOGGER.error("No vehicles found")
                    return self.async_abort(reason="no_vehicles")

                # Store vehicles for next step
                self.data[CONFIG_FLOW_TEMP_VEHICLES] = self.api_connection.vehicles
                
                # Store tokens
                self.data[CONF_DEVICE_ID] = self.api_connection.device_id
                self.data[CONF_REFRESH_TOKEN] = self.api_connection.refresh_token

                _LOGGER.info("Found %d vehicles", len(self.api_connection.vehicles))
                for v in self.api_connection.vehicles:
                    _LOGGER.info("  - %s (%s): %s", 
                                v.get("nickName"), v.get("modelName"), v.get("vehicleIdentifier"))

                return await self.async_step_pick_vehicle()

            except AuthError as e:
                _LOGGER.error("Authentication failed: %s", e)
                errors["base"] = "invalid_otp"
            except ConfigEntryAuthFailed as e:
                _LOGGER.error("Config entry auth failed: %s", e)
                errors["base"] = "auth"
            except Exception as e:
                _LOGGER.exception("Error completing login: %s", e)
                errors["base"] = "auth"

        return self.async_show_form(
            step_id="otp_code",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "otp_type": self.data.get(CONF_OTP_TYPE, "EMAIL/SMS"),
            },
        )

    async def async_step_pick_vehicle(self, user_input: dict[str, Any] | None = None):
        """Add ALL vehicles at once - no picking needed."""
        _LOGGER.debug("Adding all vehicles automatically")

        if self.api_connection is None:
            raise ConfigEntryAuthFailed("API connection not established")

        vehicles = self.data.get(CONFIG_FLOW_TEMP_VEHICLES, [])
        
        # Clean up temporary data
        self.data.pop(CONFIG_FLOW_TEMP_VEHICLES, None)
        self.data.pop(CONF_OTP_CODE, None)
        self.data.pop(CONF_OTP_TYPE, None)

        _LOGGER.info("Processing %d vehicles for setup", len(vehicles))

        # Handle reauth - just update the one entry
        if self.source == SOURCE_REAUTH:
            reauth_entry = self._get_reauth_entry()
            vehicle_id = reauth_entry.data.get(CONF_VEHICLE_ID)

            entry_data = {
                CONF_USERNAME: self.data[CONF_USERNAME],
                CONF_PASSWORD: self.data[CONF_PASSWORD],
                CONF_VEHICLE_ID: vehicle_id,
                CONF_DEVICE_ID: self.data.get(CONF_DEVICE_ID),
                CONF_REFRESH_TOKEN: self.data.get(CONF_REFRESH_TOKEN),
            }

            await self.async_set_unique_id(vehicle_id)
            self._abort_if_unique_id_mismatch()

            return self.async_update_reload_and_abort(
                reauth_entry,
                data_updates=entry_data,
            )

        # For new setup: add ALL vehicles
        created_entries = []
        for vehicle in vehicles:
            vehicle_id = vehicle["vehicleIdentifier"]
            vehicle_name = f"{vehicle['nickName']} ({vehicle['modelName']})"

            _LOGGER.info("Checking vehicle: %s (%s)", vehicle_name, vehicle_id)

            # Check if already configured
            existing_ids = self._async_current_ids()
            if vehicle_id in existing_ids:
                _LOGGER.info("Vehicle %s already configured, skipping", vehicle_name)
                continue

            # Create entry data
            entry_data = {
                CONF_USERNAME: self.data[CONF_USERNAME],
                CONF_PASSWORD: self.data[CONF_PASSWORD],
                CONF_VEHICLE_ID: vehicle_id,
                CONF_DEVICE_ID: self.data.get(CONF_DEVICE_ID),
                CONF_REFRESH_TOKEN: self.data.get(CONF_REFRESH_TOKEN),
            }

            created_entries.append((vehicle_id, vehicle_name, entry_data))

        if not created_entries:
            _LOGGER.info("All vehicles already configured")
            return self.async_abort(reason="already_configured")

        _LOGGER.info("Creating entries for %d new vehicles", len(created_entries))

        # Create first entry via flow return
        first_id, first_name, first_data = created_entries[0]
        await self.async_set_unique_id(first_id)
        self._abort_if_unique_id_configured()

        # Schedule additional entries via import flows
        for vehicle_id, vehicle_name, entry_data in created_entries[1:]:
            _LOGGER.info("Scheduling import for: %s", vehicle_name)
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": "import"},
                    data={"title": vehicle_name, **entry_data},
                )
            )

        return self.async_create_entry(title=first_name, data=first_data)

    async def async_step_import(self, import_data: dict[str, Any]):
        """Handle import of additional vehicles."""
        title = import_data.get("title", "Kia/Hyundai Vehicle")
        vehicle_id = import_data.get(CONF_VEHICLE_ID)

        _LOGGER.info("Import step for: %s (%s)", title, vehicle_id)

        if not vehicle_id:
            _LOGGER.error("Import called without vehicle_id")
            return self.async_abort(reason="unknown")

        # Check if already configured
        existing_ids = self._async_current_ids()
        if vehicle_id in existing_ids:
            _LOGGER.info("Vehicle %s already configured", vehicle_id)
            return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(vehicle_id)

        # Remove title from data
        entry_data = {k: v for k, v in import_data.items() if k != "title"}

        _LOGGER.info("Creating entry for: %s", title)
        return self.async_create_entry(title=title, data=entry_data)
