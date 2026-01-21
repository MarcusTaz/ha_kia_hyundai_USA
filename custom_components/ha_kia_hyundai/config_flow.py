"""Config flow for Kia/Hyundai US integration using EU library."""

import asyncio
import logging
import threading
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

from .const import (
    CONF_BRAND,
    CONF_PIN,
    CONF_OTP_CODE,
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

# OTP delivery method constants
CONF_OTP_METHOD = "otp_method"
OTP_METHOD_EMAIL = "EMAIL"
OTP_METHOD_PHONE = "PHONE"


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
        self.login_task: asyncio.Task | None = None
        # OTP flow state - thread-safe
        self._otp_method: str | None = None
        self._otp_method_event = threading.Event()
        self._otp_code: str | None = None
        self._otp_code_event = threading.Event()
        # OTP info from API
        self._otp_email: str | None = None
        self._otp_phone: str | None = None
        self._otp_has_email: bool = False
        self._otp_has_phone: bool = False
        # Error tracking
        self._login_error: Exception | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get options flow handler."""
        return KiaUvoOptionFlowHandler(config_entry)

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None):
        """Handle re-authentication."""
        _LOGGER.debug(f"Reauth with input: {user_input}")
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle user step - credentials input."""
        _LOGGER.debug(f"User step with input: {user_input}")

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

            # Reset OTP state
            self._otp_method = None
            self._otp_method_event.clear()
            self._otp_code = None
            self._otp_code_event.clear()
            self._login_error = None

            # Create SYNCHRONOUS OTP handler (EU library calls this synchronously)
            def otp_handler(context: dict[str, Any]) -> dict[str, Any]:
                """Handle OTP requests from the EU library.

                This is called SYNCHRONOUSLY from the EU library's login thread.
                We use threading.Event to wait for user input from the config flow.
                """
                stage = context.get("stage", "")
                _LOGGER.info(f"OTP handler called with stage: {stage}")
                _LOGGER.debug(f"OTP context: {context}")

                if stage == "choose_destination":
                    # Store available options for the UI
                    self._otp_has_email = context.get("hasEmail", False)
                    self._otp_has_phone = context.get("hasPhone", False)
                    self._otp_email = context.get("email", "")
                    self._otp_phone = context.get("phone", "")

                    _LOGGER.info(
                        f"OTP options - Email: {self._otp_email} ({self._otp_has_email}), "
                        f"Phone: {self._otp_phone} ({self._otp_has_phone})"
                    )

                    # Wait for user to choose delivery method (with timeout)
                    _LOGGER.info("Waiting for user to select OTP delivery method...")
                    if self._otp_method_event.wait(timeout=120):
                        method = self._otp_method
                        _LOGGER.info(f"User selected OTP method: {method}")
                        return {"notify_type": method}
                    else:
                        _LOGGER.error("Timeout waiting for OTP method selection")
                        return {}

                elif stage == "input_code":
                    # Wait for OTP code to be entered (with timeout)
                    _LOGGER.info("Waiting for user to enter OTP code...")
                    _LOGGER.info(f"OTP context for input_code: {context}")
                    if self._otp_code_event.wait(timeout=120):
                        code = self._otp_code
                        # Clean the code - remove any whitespace
                        if code:
                            code = code.strip()
                        _LOGGER.info(f"OTP code received: '{code[:2] if code else ''}***' (length: {len(code) if code else 0})")
                        _LOGGER.info("Returning otp_code to library")
                        result = {"otp_code": code}
                        _LOGGER.info(f"Returning: {{'otp_code': '{code[:2] if code else ''}***'}}")
                        return result
                    else:
                        _LOGGER.error("Timeout waiting for OTP code")
                        return {}

                return {}

            try:
                _LOGGER.info("Creating VehicleManager for %s (%s)", brand_name, brand)
                self.vehicle_manager = VehicleManager(
                    region=REGION_USA,
                    brand=brand,
                    username=username,
                    password=password,
                    pin=pin,
                    otp_handler=otp_handler,
                )

                # Start login in background thread via executor
                _LOGGER.info("Starting VehicleManager login (may trigger OTP)...")
                self.login_task = self.hass.async_create_task(
                    self._run_login_in_executor()
                )

                # Give the login task a moment to start and potentially call OTP handler
                await asyncio.sleep(3)

                # Proceed to OTP method selection step
                return await self.async_step_otp_method()

            except Exception as e:
                _LOGGER.exception(f"Error during login setup: {e}")
                errors["base"] = "auth"

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def _run_login_in_executor(self):
        """Run the blocking login in an executor thread."""
        try:
            _LOGGER.info("Running login in executor...")
            await self.hass.async_add_executor_job(self._do_login)
            _LOGGER.info("Login completed successfully")
        except Exception as e:
            _LOGGER.error(f"Login failed: {e}")
            self._login_error = e

    def _do_login(self):
        """Perform the actual login (blocking, runs in executor)."""
        # Note: check_and_refresh_token() calls initialize() when token is None,
        # which calls login(). We should NOT call initialize() separately as
        # that would trigger a second login attempt!
        _LOGGER.info("Starting login via check_and_refresh_token...")
        self.vehicle_manager.check_and_refresh_token()
        _LOGGER.info(
            "Login complete. Found %d vehicles",
            len(self.vehicle_manager.vehicles) if self.vehicle_manager.vehicles else 0
        )

    async def async_step_otp_method(self, user_input: dict[str, Any] | None = None):
        """Handle OTP delivery method selection."""
        _LOGGER.debug(f"OTP method step with input: {user_input}")

        errors: dict[str, str] = {}

        # Check if login already completed (no OTP needed)
        if self.login_task and self.login_task.done():
            if self._login_error:
                _LOGGER.error(f"Login failed: {self._login_error}")
                errors["base"] = "auth"
            else:
                # Login succeeded without OTP
                return await self._finalize_setup()

        # Build options based on what's available
        otp_options = {}

        if self._otp_has_email and self._otp_email:
            otp_options["EMAIL"] = f"Email ({self._otp_email})"
        if self._otp_has_phone and self._otp_phone:
            otp_options["PHONE"] = f"Phone/SMS ({self._otp_phone})"

        # Fallback if detection didn't work yet
        if not otp_options:
            otp_options = {
                "EMAIL": "Email",
                "PHONE": "Phone/SMS",
            }

        data_schema = vol.Schema({
            vol.Required(CONF_OTP_METHOD): vol.In(otp_options),
        })

        if user_input is not None:
            # Store the selected method and signal the waiting thread
            self._otp_method = user_input[CONF_OTP_METHOD]
            self._otp_method_event.set()
            _LOGGER.info(f"User selected OTP delivery: {self._otp_method}")

            # Give time for OTP to be sent
            await asyncio.sleep(2)

            # Proceed to OTP code entry
            return await self.async_step_otp_code()

        return self.async_show_form(
            step_id="otp_method",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_otp_code(self, user_input: dict[str, Any] | None = None):
        """Handle OTP code entry."""
        _LOGGER.debug(f"OTP code step with input: {user_input}")

        data_schema = vol.Schema({
            vol.Required(CONF_OTP_CODE): str,
        })
        errors: dict[str, str] = {}

        if user_input is not None:
            # Store OTP code and signal the waiting thread
            self._otp_code = user_input[CONF_OTP_CODE]
            self._otp_code_event.set()
            _LOGGER.info("OTP code submitted, waiting for login to complete...")

            try:
                # Wait for the login task to complete
                await asyncio.wait_for(self.login_task, timeout=60)

                if self._login_error:
                    _LOGGER.error(f"Login failed: {self._login_error}")
                    errors["base"] = "auth"
                else:
                    return await self._finalize_setup()

            except asyncio.TimeoutError:
                _LOGGER.error("Timeout waiting for login to complete")
                errors["base"] = "timeout"
            except Exception as e:
                _LOGGER.exception(f"Error during OTP verification: {e}")
                errors["base"] = "auth"

        method_desc = "email" if self._otp_method == "EMAIL" else "phone"
        return self.async_show_form(
            step_id="otp_code",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "method": method_desc,
            },
        )

    async def _finalize_setup(self):
        """Finalize setup after successful login."""
        if self.vehicle_manager is None or not self.vehicle_manager.vehicles:
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

            _LOGGER.info("Preparing to add vehicle: %s (%s)", vehicle_name, vehicle_id)

            # Check if this vehicle is already configured
            existing_entry = await self.async_set_unique_id(vehicle_id)
            if existing_entry:
                _LOGGER.info("Vehicle %s already configured, skipping", vehicle_name)
                continue

            # Create entry data for this vehicle
            entry_data = {
                CONF_USERNAME: self.data[CONF_USERNAME],
                CONF_PASSWORD: self.data[CONF_PASSWORD],
                CONF_VEHICLE_ID: vehicle_id,
                CONF_BRAND: self.data[CONF_BRAND],
                CONF_PIN: self.data.get(CONF_PIN, ""),
            }

            created_entries.append((vehicle_name, entry_data))

        if not created_entries:
            return self.async_abort(reason="already_configured")

        _LOGGER.info("Creating entries for %d new vehicles", len(created_entries))

        # Create first entry via flow return (required by HA)
        first_name, first_data = created_entries[0]

        # Schedule additional entries via import flows
        for vehicle_name, entry_data in created_entries[1:]:
            _LOGGER.info("Scheduling auto-add for vehicle: %s", vehicle_name)
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

        if not vehicle_id:
            return self.async_abort(reason="unknown")

        await self.async_set_unique_id(vehicle_id)
        self._abort_if_unique_id_configured()

        # Remove title from data before saving (it's not a config field)
        entry_data = {k: v for k, v in import_data.items() if k != "title"}

        _LOGGER.info("Import creating entry: %s", title)
        return self.async_create_entry(title=title, data=entry_data)
