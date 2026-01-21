"""Config flow for Kia/Hyundai US integration using EU library.

This uses the same OTP flow as the official kia_uvo integration:
1. login() returns OTPRequest if OTP needed
2. send_otp(method) sends OTP to selected destination
3. verify_otp_and_complete_login(code) completes authentication
"""

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

from hyundai_kia_connect_api import VehicleManager
from hyundai_kia_connect_api.ApiImpl import OTPRequest
from hyundai_kia_connect_api.const import OTP_NOTIFY_TYPE
from hyundai_kia_connect_api.exceptions import AuthenticationError

from .const import (
    CONF_BRAND,
    CONF_PIN,
    CONF_TOKEN,
    DOMAIN,
    CONFIG_FLOW_VERSION,
    CONF_VEHICLE_ID,
    DEFAULT_SCAN_INTERVAL,
    CONFIG_FLOW_TEMP_VEHICLES,
    REGION_USA,
    BRANDS,
    BRAND_KIA,
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
        self.vehicle_manager: VehicleManager | None = None
        self._otp_request: OTPRequest | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get options flow handler."""
        return KiaUvoOptionFlowHandler(config_entry)

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None):
        """Handle re-authentication."""
        _LOGGER.debug("Reauth with input: %s", user_input)
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle user step - credentials input."""
        _LOGGER.debug("User step with input: %s", user_input)

        data_schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_BRAND, default="Kia"): vol.In(list(BRANDS.keys())),
            vol.Optional(CONF_PIN, default=""): str,
        })
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            brand_name = user_input[CONF_BRAND]
            brand = BRANDS.get(brand_name, BRAND_KIA)
            pin = user_input.get(CONF_PIN, "")

            # Store user input
            self.data = {
                CONF_USERNAME: username,
                CONF_PASSWORD: password,
                CONF_BRAND: brand,
                CONF_PIN: pin,
            }

            try:
                _LOGGER.info("Creating VehicleManager for %s (%s)", brand_name, brand)
                self.vehicle_manager = VehicleManager(
                    region=REGION_USA,
                    brand=brand,
                    username=username,
                    password=password,
                    pin=pin,
                    # NO otp_handler - we use explicit methods instead
                )

                # Attempt login - returns Token or OTPRequest
                _LOGGER.info("Attempting login...")
                result = await self.hass.async_add_executor_job(
                    self.vehicle_manager.login
                )

                if isinstance(result, OTPRequest):
                    # OTP is required
                    _LOGGER.info("OTP required. Email: %s, SMS: %s",
                                 result.has_email, result.has_sms)
                    self._otp_request = result
                    return await self.async_step_select_otp_method()
                else:
                    # Login succeeded without OTP (cached token)
                    _LOGGER.info("Login succeeded without OTP")
                    # Save the token for later use
                    if self.vehicle_manager.token:
                        self.data[CONF_TOKEN] = self.vehicle_manager.token.to_dict()
                        _LOGGER.info("Token saved for future authentication")
                    return await self._finalize_setup()

            except AuthenticationError as e:
                _LOGGER.error("Authentication error: %s", e)
                errors["base"] = "auth"
            except Exception as e:
                _LOGGER.exception("Error during login: %s", e)
                errors["base"] = "auth"

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_select_otp_method(self, user_input: dict[str, Any] | None = None):
        """Let user choose email or SMS for OTP delivery."""
        _LOGGER.debug("OTP method step with input: %s", user_input)

        errors: dict[str, str] = {}

        # Build available methods
        otp_methods = {}
        if self._otp_request and self._otp_request.has_email:
            otp_methods["EMAIL"] = "Email"
        if self._otp_request and self._otp_request.has_sms:
            otp_methods["SMS"] = "Phone/SMS"

        # Fallback if detection failed
        if not otp_methods:
            otp_methods = {"EMAIL": "Email", "SMS": "Phone/SMS"}

        data_schema = vol.Schema({
            vol.Required("method"): vol.In(otp_methods),
        })

        if user_input is not None:
            method = user_input["method"]
            _LOGGER.info("User selected OTP method: %s", method)

            try:
                # Use the proper enum from the library
                if method == "EMAIL":
                    otp_type = OTP_NOTIFY_TYPE.EMAIL
                else:
                    otp_type = OTP_NOTIFY_TYPE.SMS

                # Send OTP using explicit method (same as official kia_uvo)
                _LOGGER.info("Sending OTP via %s (type=%s)...", method, otp_type)
                await self.hass.async_add_executor_job(
                    self.vehicle_manager.send_otp,
                    otp_type
                )
                _LOGGER.info("OTP sent successfully")

                return await self.async_step_enter_otp()

            except Exception as e:
                _LOGGER.exception("Error sending OTP: %s", e)
                errors["base"] = "auth"

        return self.async_show_form(
            step_id="select_otp_method",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_enter_otp(self, user_input: dict[str, Any] | None = None):
        """Prompt user to enter the OTP code."""
        _LOGGER.debug("Enter OTP step with input: %s", user_input)

        data_schema = vol.Schema({
            vol.Required("otp"): str,
        })
        errors: dict[str, str] = {}

        if user_input is not None:
            otp_code = user_input["otp"].strip()
            _LOGGER.info("Verifying OTP code (length: %d)...", len(otp_code))

            try:
                # Verify OTP and complete login using explicit method
                await self.hass.async_add_executor_job(
                    self.vehicle_manager.verify_otp_and_complete_login,
                    otp_code
                )
                _LOGGER.info("OTP verified successfully!")

                # Save the token for later use (avoids OTP on restart)
                if self.vehicle_manager.token:
                    self.data[CONF_TOKEN] = self.vehicle_manager.token.to_dict()
                    _LOGGER.info("Token saved for future authentication")

                return await self._finalize_setup()

            except AuthenticationError as e:
                _LOGGER.error("OTP verification failed: %s", e)
                errors["base"] = "invalid_otp"
            except Exception as e:
                _LOGGER.exception("Error verifying OTP: %s", e)
                errors["base"] = "auth"

        return self.async_show_form(
            step_id="enter_otp",
            data_schema=data_schema,
            errors=errors,
        )

    async def _finalize_setup(self):
        """Finalize setup after successful login."""
        _LOGGER.info("Finalizing setup...")

        try:
            # Initialize vehicles
            await self.hass.async_add_executor_job(
                self.vehicle_manager.initialize_vehicles
            )

            if not self.vehicle_manager.vehicles:
                _LOGGER.error("No vehicles found after login")
                return self.async_abort(reason="no_vehicles")

            # Build vehicles list
            vehicles = []
            for vid, vehicle in self.vehicle_manager.vehicles.items():
                _LOGGER.info(
                    "Discovered vehicle: id=%s, name=%s, model=%s",
                    vid, vehicle.name, vehicle.model
                )
                vehicles.append({
                    "vehicleIdentifier": vid,
                    "nickName": vehicle.name,
                    "modelName": vehicle.model,
                })

            self.data[CONFIG_FLOW_TEMP_VEHICLES] = vehicles
            return await self.async_step_pick_vehicle()

        except Exception as e:
            _LOGGER.exception("Error initializing vehicles: %s", e)
            return self.async_abort(reason="unknown")

    async def async_step_pick_vehicle(self, user_input: dict[str, Any] | None = None):
        """Add ALL vehicles at once - no picking needed."""
        _LOGGER.debug("Adding all vehicles automatically")

        if self.vehicle_manager is None:
            raise ConfigEntryAuthFailed("VehicleManager not established")

        vehicles = self.data.get(CONFIG_FLOW_TEMP_VEHICLES, [])
        if CONFIG_FLOW_TEMP_VEHICLES in self.data:
            del self.data[CONFIG_FLOW_TEMP_VEHICLES]

        _LOGGER.info("Processing %d vehicles for setup", len(vehicles))

        # Handle reauth - just update the one entry
        if self.source == SOURCE_REAUTH:
            reauth_entry = self._get_reauth_entry()
            vehicle_id = reauth_entry.data.get(CONF_VEHICLE_ID)

            entry_data = {
                CONF_USERNAME: self.data[CONF_USERNAME],
                CONF_PASSWORD: self.data[CONF_PASSWORD],
                CONF_VEHICLE_ID: vehicle_id,
                CONF_BRAND: self.data[CONF_BRAND],
                CONF_PIN: self.data.get(CONF_PIN, ""),
                CONF_TOKEN: self.data.get(CONF_TOKEN),  # Include saved token
            }

            await self.async_set_unique_id(vehicle_id)
            self._abort_if_unique_id_mismatch()

            return self.async_update_reload_and_abort(
                reauth_entry,
                data_updates=entry_data,
            )

        # For new setup: add ALL vehicles
        # First, check which vehicles are already configured
        created_entries = []
        for vehicle in vehicles:
            vehicle_id = vehicle["vehicleIdentifier"]
            vehicle_name = f"{vehicle['nickName']} ({vehicle['modelName']})"

            _LOGGER.info("Checking vehicle: %s (%s)", vehicle_name, vehicle_id)

            # Check if this vehicle is already configured using _async_current_ids
            existing_ids = self._async_current_ids()
            if vehicle_id in existing_ids:
                _LOGGER.info("Vehicle %s already configured (id in current_ids), skipping", vehicle_name)
                continue

            # Create entry data for this vehicle
            entry_data = {
                CONF_USERNAME: self.data[CONF_USERNAME],
                CONF_PASSWORD: self.data[CONF_PASSWORD],
                CONF_VEHICLE_ID: vehicle_id,
                CONF_BRAND: self.data[CONF_BRAND],
                CONF_PIN: self.data.get(CONF_PIN, ""),
                CONF_TOKEN: self.data.get(CONF_TOKEN),  # Include saved token
            }

            created_entries.append((vehicle_id, vehicle_name, entry_data))

        if not created_entries:
            _LOGGER.info("All vehicles already configured")
            return self.async_abort(reason="already_configured")

        _LOGGER.info("Creating entries for %d new vehicles: %s",
                    len(created_entries),
                    [name for _, name, _ in created_entries])

        # Create first entry via flow return (required by HA)
        first_id, first_name, first_data = created_entries[0]

        # Set unique_id for first entry
        await self.async_set_unique_id(first_id)
        self._abort_if_unique_id_configured()

        # Schedule additional entries via import flows with a small delay
        # to avoid race conditions
        async def schedule_import(vehicle_id: str, vehicle_name: str, entry_data: dict):
            """Schedule an import flow for a vehicle."""
            try:
                _LOGGER.info("Starting import flow for vehicle: %s (%s)", vehicle_name, vehicle_id)
                result = await self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": "import"},
                    data={"title": vehicle_name, **entry_data},
                )
                _LOGGER.info("Import flow result for %s: %s", vehicle_name, result)
            except Exception as e:
                _LOGGER.error("Failed to import vehicle %s: %s", vehicle_name, e)

        for vehicle_id, vehicle_name, entry_data in created_entries[1:]:
            _LOGGER.info("Scheduling import for vehicle: %s", vehicle_name)
            self.hass.async_create_task(
                schedule_import(vehicle_id, vehicle_name, entry_data)
            )

        return self.async_create_entry(title=first_name, data=first_data)

    async def async_step_import(self, import_data: dict[str, Any]):
        """Handle import of additional vehicles."""
        title = import_data.get("title", "Kia/Hyundai Vehicle")
        vehicle_id = import_data.get(CONF_VEHICLE_ID)

        _LOGGER.info("Import step called for: %s (vehicle_id=%s)", title, vehicle_id)

        if not vehicle_id:
            _LOGGER.error("Import called without vehicle_id")
            return self.async_abort(reason="unknown")

        # Check if already configured
        existing_ids = self._async_current_ids()
        if vehicle_id in existing_ids:
            _LOGGER.info("Vehicle %s already configured, aborting import", vehicle_id)
            return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(vehicle_id)
        # Don't use _abort_if_unique_id_configured as it raises - use gentler check
        if self._async_current_entries():
            for entry in self._async_current_entries():
                if entry.unique_id == vehicle_id:
                    _LOGGER.info("Vehicle %s has matching entry, aborting import", vehicle_id)
                    return self.async_abort(reason="already_configured")

        # Remove title from data before saving (it's not a config field)
        entry_data = {k: v for k, v in import_data.items() if k != "title"}

        _LOGGER.info("Import creating entry for: %s (id=%s)", title, vehicle_id)
        return self.async_create_entry(title=title, data=entry_data)
