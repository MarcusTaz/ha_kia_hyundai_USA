import asyncio
import logging
from sqlite3 import DataError
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
from kia_hyundai_api import UsKia

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
from . import patch_api_headers

_LOGGER = logging.getLogger(__name__)

class OneTimePasswordStarted(Exception):
    pass


class KiaUvoOptionFlowHandler(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
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
        if user_input is not None:
            _LOGGER.debug("user input in option flow : %s", user_input)
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(step_id="init", data_schema=self.schema)


@config_entries.HANDLERS.register(DOMAIN)
class KiaUvoConfigFlowHandler(config_entries.ConfigFlow):

    VERSION = CONFIG_FLOW_VERSION
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    data: dict[str, Any] = {}
    otp_key: str | None = None
    api_connection: UsKia | None = None
    last_action: dict[str, Any] | None = None
    notify_type: str | None = None


    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return KiaUvoOptionFlowHandler(config_entry)

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None):
        _LOGGER.debug(f"Reauth with input: {user_input}")
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        _LOGGER.debug(f"User step with input: {user_input}")
        data_schema = {
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_OTP_TYPE, default="SMS"): vol.In(["EMAIL", "SMS"]),
        }
        errors: dict[str, str] = {}

        if user_input is not None and CONF_OTP_TYPE in user_input:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            otp_type = user_input[CONF_OTP_TYPE]
            async def otp_callback(context: dict[str, Any]):
                _LOGGER.info(f"OTP callback called with stage: {context.get('stage')}")
                if context["stage"] == "choose_destination":
                    _LOGGER.info(f"OTP choose_destination - returning notify_type: {otp_type}")
                    _LOGGER.debug(f"Full OTP context: {context}")
                    return { "notify_type": otp_type }
                if context["stage"] == "input_code":
                    _LOGGER.info("OTP input_code stage - waiting for user to enter code")
                    loop_counter = 0
                    while loop_counter < 120:
                        _LOGGER.debug(f"data: {self.data}")
                        if CONF_OTP_CODE in self.data:
                            _LOGGER.debug(f"OTP code: {self.data[CONF_OTP_CODE]}")
                            return { "otp_code": self.data[CONF_OTP_CODE] }
                        loop_counter += 1
                        _LOGGER.debug(f"Waiting for OTP {loop_counter}")
                        _LOGGER.debug(f"data: {self.data}")
                        await asyncio.sleep(1)
                    raise ConfigEntryAuthFailed("2 minute timeout waiting for OTP")

            try:
                client_session = async_get_clientsession(self.hass)
                _LOGGER.info("Creating UsKia connection...")
                self.api_connection = UsKia(
                    username=username,
                    password=password,
                    otp_callback=otp_callback,
                    client_session=client_session,
                )
                _LOGGER.info(f"UsKia created with device_id: {self.api_connection.device_id}")
                
                # Patch the API headers with working iOS headers
                _LOGGER.info("Patching API headers...")
                patch_api_headers(self.api_connection)
                _LOGGER.info("Headers patched successfully")
                
                self.data.update(user_input)
                _LOGGER.info("Starting login task...")
                self.otp_task = self.hass.loop.create_task(self.api_connection.login())
                _LOGGER.info("Login task started, proceeding to OTP code step")
                return await self.async_step_otp_code()
            except ConfigEntryAuthFailed as e:
                _LOGGER.error(f"ConfigEntryAuthFailed: {e}")
                errors["base"] = "auth"
            except Exception as e:
                _LOGGER.exception(f"Unexpected error during login setup: {e}")
                errors["base"] = "auth"

        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(data_schema), errors=errors
        )

    async def async_step_otp_code(
        self, user_input: dict[str, Any] | None = None
    ):
        _LOGGER.debug(f"OTP code step with input: {user_input}")
        data_schema = {
            vol.Required(CONF_OTP_CODE): str,
        }
        errors: dict[str, str] = {}
        if user_input is not None:
            self.data.update(user_input)
            try:
                await self.otp_task
            except DataError:
                raise ConfigEntryAuthFailed("Invalid OTP code")
            if self.api_connection is None:
                raise ConfigEntryAuthFailed("API connection not established")
            await self.api_connection.get_vehicles()
            self.data[CONFIG_FLOW_TEMP_VEHICLES] = self.api_connection.vehicles
            return await self.async_step_pick_vehicle()
        return self.async_show_form(
            step_id="otp_code", data_schema=vol.Schema(data_schema), errors=errors
        )


    async def async_step_pick_vehicle(
        self, user_input: dict[str, Any] | None = None
    ):
        """Add ALL vehicles at once - no picking needed."""
        _LOGGER.debug(f"Adding all vehicles automatically")
        
        if self.api_connection is None:
            raise ConfigEntryAuthFailed("API connection not established")
        
        vehicles = self.data[CONFIG_FLOW_TEMP_VEHICLES]
        del self.data[CONFIG_FLOW_TEMP_VEHICLES]
        
        # Handle reauth - just update the one entry
        if self.source == SOURCE_REAUTH:
            reauth_entry = self._get_reauth_entry()
            vehicle_id = reauth_entry.data.get(CONF_VEHICLE_ID)
            self.data[CONF_VEHICLE_ID] = vehicle_id
            self.data[CONF_REFRESH_TOKEN] = self.api_connection.refresh_token
            self.data[CONF_DEVICE_ID] = self.api_connection.device_id
            await self.async_set_unique_id(vehicle_id)
            self._abort_if_unique_id_mismatch()
            return self.async_update_reload_and_abort(
                reauth_entry,
                data_updates=self.data,
            )
        
        # For new setup: add ALL vehicles
        created_entries = []
        for vehicle in vehicles:
            vehicle_id = vehicle["vehicleIdentifier"]
            vehicle_name = f"{vehicle['nickName']} ({vehicle['modelName']})"
            
            # Check if this vehicle is already configured
            existing_entry = await self.async_set_unique_id(vehicle_id)
            if existing_entry:
                _LOGGER.debug(f"Vehicle {vehicle_name} already configured, skipping")
                continue
            
            # Create entry data for this vehicle
            entry_data = {
                CONF_USERNAME: self.data[CONF_USERNAME],
                CONF_PASSWORD: self.data[CONF_PASSWORD],
                CONF_VEHICLE_ID: vehicle_id,
                CONF_REFRESH_TOKEN: self.api_connection.refresh_token,
                CONF_DEVICE_ID: self.api_connection.device_id,
            }
            if CONF_OTP_TYPE in self.data:
                entry_data[CONF_OTP_TYPE] = self.data[CONF_OTP_TYPE]
            
            created_entries.append((vehicle_name, entry_data))
        
        if not created_entries:
            return self.async_abort(reason="already_configured")
        
        # Create first entry via flow return (required by HA)
        first_name, first_data = created_entries[0]
        
        # Schedule additional entries via import flows (import is a valid HA source)
        for vehicle_name, entry_data in created_entries[1:]:
            _LOGGER.info(f"Scheduling auto-add for vehicle: {vehicle_name}")
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
        title = import_data.get("title", "Kia Vehicle")
        vehicle_id = import_data.get(CONF_VEHICLE_ID)
        
        if not vehicle_id:
            return self.async_abort(reason="unknown")
        
        await self.async_set_unique_id(vehicle_id)
        self._abort_if_unique_id_configured()
        
        # Remove title from data before saving (it's not a config field)
        entry_data = {k: v for k, v in import_data.items() if k != "title"}
        
        _LOGGER.info(f"Import creating entry: {title}")
        return self.async_create_entry(title=title, data=entry_data)
