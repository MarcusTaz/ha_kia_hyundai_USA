"""Config flow for Kia/Hyundai/Genesis US integration.

Architecture:
- ONE config entry per account (username + brand as unique_id)
- Multiple vehicles stored in the entry's data
- Each vehicle becomes a separate device in Home Assistant

Authentication flows:
- Kia: OTP-based (username, password, OTP code via EMAIL/SMS)
- Hyundai: PIN-based (username, password, 4-digit PIN)
- Genesis: PIN-based (username, password, 4-digit PIN)
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

# Use embedded API libraries
from .kia_hyundai_api import UsKia, AuthError
from .kia_hyundai_api.us_hyundai import UsHyundai
from .kia_hyundai_api.us_genesis import UsGenesis

from .const import (
    CONF_BRAND,
    CONF_DEVICE_ID,
    CONF_OTP_CODE,
    CONF_OTP_TYPE,
    CONF_PIN,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    CONFIG_FLOW_VERSION,
    CONF_VEHICLE_ID,
    CONF_VEHICLES,
    DEFAULT_SCAN_INTERVAL,
    CONFIG_FLOW_TEMP_VEHICLES,
    BRAND_KIA,
    BRAND_HYUNDAI,
    BRAND_GENESIS,
    BRANDS,
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
    """Handle config flow for Kia/Hyundai/Genesis US."""

    VERSION = CONFIG_FLOW_VERSION
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        """Initialize config flow."""
        self.data: dict[str, Any] = {}
        self.api_connection: UsKia | UsHyundai | UsGenesis | None = None
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
        # Store the existing entry data for reference (e.g., username, brand)
        if user_input is not None:
            self.data[CONF_USERNAME] = user_input.get(CONF_USERNAME, "")
            self.data[CONF_BRAND] = user_input.get(CONF_BRAND, BRAND_KIA)
        # Show the brand selection form
        return await self.async_step_user(None)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle user step - brand selection."""
        _LOGGER.debug("User (brand selection) step with input: %s", user_input)

        # Get default brand from stored data (e.g., from reauth)
        default_brand = self.data.get(CONF_BRAND, BRAND_KIA)
        
        data_schema = vol.Schema({
            vol.Required(CONF_BRAND, default=default_brand): vol.In(BRANDS),
        })
        errors: dict[str, str] = {}

        if user_input is not None:
            brand = user_input[CONF_BRAND]
            self.data[CONF_BRAND] = brand
            
            # Route to brand-specific credential step
            if brand == BRAND_KIA:
                return await self.async_step_kia_credentials()
            else:  # Hyundai or Genesis
                return await self.async_step_bluelink_credentials()

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_kia_credentials(self, user_input: dict[str, Any] | None = None):
        """Handle Kia credentials input (with OTP)."""
        _LOGGER.debug("Kia credentials step with input: %s", user_input)

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

            # Check if this account is already configured (not during reauth)
            unique_id = f"{BRAND_KIA}_{username.lower()}"
            if self.source != SOURCE_REAUTH:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

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
                self.data.update({
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                    CONF_OTP_TYPE: otp_type,
                    CONF_BRAND: BRAND_KIA,
                })

                # Start login task (runs in background while waiting for OTP)
                _LOGGER.info("Starting login task...")
                self.otp_task = self.hass.loop.create_task(self.api_connection.login())
                
                return await self.async_step_otp_code()

            except AuthError as e:
                _LOGGER.error("Authentication error: %s", e)
                errors["base"] = "auth"
            except Exception as e:
                _LOGGER.exception("Error during login setup: %s", e)
                errors["base"] = "auth"

        return self.async_show_form(
            step_id="kia_credentials",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_bluelink_credentials(self, user_input: dict[str, Any] | None = None):
        """Handle Hyundai/Genesis credentials input (PIN-based, no OTP)."""
        brand = self.data.get(CONF_BRAND, BRAND_HYUNDAI)
        brand_name = BRANDS.get(brand, "Hyundai")
        
        _LOGGER.debug("%s credentials step with input: %s", brand_name, user_input)

        default_username = self.data.get(CONF_USERNAME, "")
        
        data_schema = vol.Schema({
            vol.Required(CONF_USERNAME, default=default_username): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_PIN): str,
        })
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            pin = user_input[CONF_PIN]

            # Validate PIN format (should be 4 digits)
            if not pin.isdigit() or len(pin) != 4:
                errors["base"] = "invalid_pin"
            else:
                # Check if this account is already configured (not during reauth)
                unique_id = f"{brand}_{username.lower()}"
                if self.source != SOURCE_REAUTH:
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                try:
                    client_session = async_get_clientsession(self.hass)
                    
                    if brand == BRAND_HYUNDAI:
                        _LOGGER.info("Creating UsHyundai connection for %s", username)
                        self.api_connection = UsHyundai(
                            username=username,
                            password=password,
                            pin=pin,
                            client_session=client_session,
                        )
                    else:  # Genesis
                        _LOGGER.info("Creating UsGenesis connection for %s", username)
                        self.api_connection = UsGenesis(
                            username=username,
                            password=password,
                            pin=pin,
                            client_session=client_session,
                        )
                    
                    _LOGGER.info("%s connection created with device_id: %s", 
                                brand_name, self.api_connection.device_id)

                    # Store user input
                    self.data.update({
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_PIN: pin,
                        CONF_BRAND: brand,
                    })

                    # Login and get vehicles directly (no OTP needed for Hyundai/Genesis)
                    _LOGGER.info("Logging in to %s...", brand_name)
                    await self.api_connection.login()
                    
                    _LOGGER.info("Getting vehicles...")
                    await self.api_connection.get_vehicles()
                    
                    if not self.api_connection.vehicles:
                        _LOGGER.error("No vehicles found")
                        return self.async_abort(reason="no_vehicles")

                    # Store discovered vehicles
                    self.data[CONFIG_FLOW_TEMP_VEHICLES] = self.api_connection.vehicles
                    self.data[CONF_DEVICE_ID] = self.api_connection.device_id
                    
                    if hasattr(self.api_connection, 'refresh_token') and self.api_connection.refresh_token:
                        self.data[CONF_REFRESH_TOKEN] = self.api_connection.refresh_token

                    _LOGGER.info("Found %d vehicles", len(self.api_connection.vehicles))
                    for v in self.api_connection.vehicles:
                        _LOGGER.info("  - %s: %s", v.get("nickName", "Unknown"), v.get("id", ""))

                    # Go directly to vehicle confirmation (skip OTP step)
                    return await self.async_step_confirm_vehicles()

                except AuthError as e:
                    _LOGGER.error("Authentication error: %s", e)
                    errors["base"] = "auth"
                except Exception as e:
                    _LOGGER.exception("Error during login: %s", e)
                    errors["base"] = "auth"

        return self.async_show_form(
            step_id="bluelink_credentials",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "brand": brand_name,
            },
        )

    async def async_step_otp_code(self, user_input: dict[str, Any] | None = None):
        """Handle OTP code input step."""
        _LOGGER.debug("OTP code step with input: %s", user_input)
        
        brand = self.data.get(CONF_BRAND, BRAND_KIA)

        data_schema = vol.Schema({
            vol.Required(CONF_OTP_CODE): str,
        })
        errors: dict[str, str] = {}

        # Check if the task already completed (no OTP needed for some Hyundai/Genesis accounts)
        if self.otp_task is not None and self.otp_task.done():
            try:
                # Task already finished - check for errors
                self.otp_task.result()  # This will raise if there was an exception
                _LOGGER.info("Login completed without OTP!")
                return await self._finalize_login()
            except AuthError as e:
                if "OTP required" in str(e):
                    _LOGGER.info("OTP is required, showing OTP form")
                    # Continue to show OTP form
                else:
                    _LOGGER.error("Authentication failed: %s", e)
                    errors["base"] = "auth"
                    return self.async_show_form(
                        step_id="otp_code",
                        data_schema=data_schema,
                        errors=errors,
                        description_placeholders={
                            "otp_type": self.data.get(CONF_OTP_TYPE, "EMAIL/SMS"),
                        },
                    )
            except Exception as e:
                _LOGGER.exception("Error during login: %s", e)
                errors["base"] = "auth"

        if user_input is not None:
            # Store the OTP code so the callback can read it
            self.data[CONF_OTP_CODE] = user_input[CONF_OTP_CODE].strip()
            _LOGGER.info("OTP code stored, waiting for login to complete...")

            try:
                # Wait for login task to complete
                await self.otp_task
                _LOGGER.info("Login completed successfully!")
                
                return await self._finalize_login()

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

    async def _finalize_login(self):
        """Finalize login and move to vehicle confirmation."""
        if self.api_connection is None:
            raise ConfigEntryAuthFailed("API connection not established")

        brand = self.data.get(CONF_BRAND, BRAND_KIA)
        
        # For Kia, we need to get vehicles after login
        # For Hyundai/Genesis, vehicles are already fetched in _bluelink_login_and_get_vehicles
        if brand == BRAND_KIA:
            _LOGGER.info("Getting vehicles...")
            await self.api_connection.get_vehicles()
        
        if not self.api_connection.vehicles:
            _LOGGER.error("No vehicles found")
            return self.async_abort(reason="no_vehicles")

        # Store discovered vehicles for confirmation step
        self.data[CONFIG_FLOW_TEMP_VEHICLES] = self.api_connection.vehicles
        
        # Store tokens
        self.data[CONF_DEVICE_ID] = self.api_connection.device_id
        if hasattr(self.api_connection, 'refresh_token') and self.api_connection.refresh_token:
            self.data[CONF_REFRESH_TOKEN] = self.api_connection.refresh_token

        _LOGGER.info("Found %d vehicles", len(self.api_connection.vehicles))
        for v in self.api_connection.vehicles:
            _LOGGER.info("  - %s (%s): %s", 
                        v.get("nickName", v.get("name")), 
                        v.get("modelName", v.get("modelCode")), 
                        v.get("vehicleIdentifier", v.get("id")))

        return await self.async_step_confirm_vehicles()

    async def async_step_confirm_vehicles(self, user_input: dict[str, Any] | None = None):
        """Show discovered vehicles and confirm setup."""
        _LOGGER.debug("Confirm vehicles step")

        vehicles = self.data.get(CONFIG_FLOW_TEMP_VEHICLES, [])
        brand = self.data.get(CONF_BRAND, BRAND_KIA)
        brand_name = BRANDS.get(brand, "Kia")
        
        # Build list of vehicle names for description
        vehicle_list = []
        for v in vehicles:
            nick = v.get("nickName", v.get("name", "Unknown"))
            model = v.get("modelName", v.get("modelCode", v.get("model", "")))
            year = v.get("modelYear", v.get("year", ""))
            vehicle_list.append(f"• {nick} ({year} {model})")
        
        vehicle_description = "\n".join(vehicle_list)

        if user_input is not None:
            # User confirmed - proceed to create entry
            _LOGGER.info("User confirmed vehicles, creating config entry")
            
            # Build vehicle list for storage (handle different field names by brand)
            vehicle_data = []
            for v in vehicles:
                vehicle_data.append({
                    "id": v.get("vehicleIdentifier", v.get("id", v.get("regid", ""))),
                    "name": v.get("nickName", v.get("name", "Unknown")),
                    "model": v.get("modelName", v.get("modelCode", v.get("model", "Unknown"))),
                    "year": v.get("modelYear", v.get("year", "")),
                    "vin": v.get("vin", v.get("VIN", "")),
                    "key": v.get("vehicleKey", v.get("regid", "")),
                })
            
            # Build entry data based on brand
            entry_data = {
                CONF_BRAND: brand,
                CONF_USERNAME: self.data[CONF_USERNAME],
                CONF_PASSWORD: self.data[CONF_PASSWORD],
                CONF_VEHICLES: vehicle_data,
                CONF_DEVICE_ID: self.data.get(CONF_DEVICE_ID),
            }
            
            # Add brand-specific fields
            if brand == BRAND_KIA:
                entry_data[CONF_REFRESH_TOKEN] = self.data.get(CONF_REFRESH_TOKEN)
            else:  # Hyundai or Genesis
                entry_data[CONF_PIN] = self.data.get(CONF_PIN)
            
            # Handle reauth - update existing entry
            if self.source == SOURCE_REAUTH:
                reauth_entry = self._get_reauth_entry()

                unique_id = f"{brand}_{self.data[CONF_USERNAME].lower()}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_mismatch()

                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates=entry_data,
                )

            # For new setup: create single entry for account with all vehicles
            # Clean up temporary data
            self.data.pop(CONFIG_FLOW_TEMP_VEHICLES, None)
            self.data.pop(CONF_OTP_CODE, None)
            self.data.pop(CONF_OTP_TYPE, None)

            # Set unique_id to brand + username (one entry per account per brand)
            unique_id = f"{brand}_{self.data[CONF_USERNAME].lower()}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            title = f"{brand_name}: {self.data[CONF_USERNAME]}"
            _LOGGER.info("Creating config entry for %s with %d vehicles", 
                        title, len(vehicle_data))

            return self.async_create_entry(
                title=title,
                data=entry_data,
            )

        # Show confirmation form with vehicle list
        return self.async_show_form(
            step_id="confirm_vehicles",
            data_schema=vol.Schema({}),  # Empty schema - just a confirmation button
            description_placeholders={
                "brand": brand_name,
                "vehicle_count": str(len(vehicles)),
                "vehicle_list": vehicle_description,
            },
        )

    async def async_step_import(self, import_data: dict[str, Any]):
        """Handle import from legacy config entries.
        
        This migrates old per-vehicle entries to the new per-account format.
        """
        _LOGGER.info("Import step called - legacy migration")
        
        # If this is a legacy import with vehicle_id, abort - 
        # migration should be handled in __init__.py
        if CONF_VEHICLE_ID in import_data:
            _LOGGER.info("Legacy vehicle entry import - will be migrated")
            return self.async_abort(reason="legacy_migration")
        
        return self.async_abort(reason="unknown")
