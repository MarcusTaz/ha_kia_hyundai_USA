"""Config flow for Kia/Hyundai US integration using EU library."""

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
        self.otp_task: asyncio.Task | None = None
        # OTP flow state
        self._otp_method: str | None = None
        self._otp_email: str | None = None
        self._otp_phone: str | None = None
        self._otp_has_email: bool = False
        self._otp_has_phone: bool = False

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

            # Create OTP handler that interacts with the config flow
            async def otp_handler(context: dict[str, Any]) -> dict[str, Any]:
                """Handle OTP requests from the EU library."""
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

                    # Wait for user to choose delivery method
                    loop_counter = 0
                    while loop_counter < 120:  # 2 minute timeout
                        if self._otp_method is not None:
                            method = self._otp_method
                            _LOGGER.info(f"User selected OTP method: {method}")
                            return {"notify_type": method}
                        loop_counter += 1
                        await asyncio.sleep(1)

                    raise ConfigEntryAuthFailed("Timeout waiting for OTP method selection")

                elif stage == "input_code":
                    # Wait for OTP code to be entered
                    loop_counter = 0
                    while loop_counter < 120:  # 2 minute timeout
                        if CONF_OTP_CODE in self.data:
                            otp_code = self.data[CONF_OTP_CODE]
                            _LOGGER.info(f"OTP code received: {otp_code[:2]}***")
                            return {"otp_code": otp_code}
                        loop_counter += 1
                        await asyncio.sleep(1)

                    raise ConfigEntryAuthFailed("Timeout waiting for OTP code")

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

                # Start initialization in background - this will trigger OTP
                _LOGGER.info("Starting VehicleManager initialization (may trigger OTP)...")
                self.otp_task = self.hass.loop.create_task(
                    self._initialize_and_get_vehicles()
                )

                # Short delay to let the OTP handler receive the choose_destination call
                await asyncio.sleep(2)

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

    async def _initialize_and_get_vehicles(self):
        """Initialize VehicleManager and fetch vehicles."""
        if self.vehicle_manager is None:
            raise ConfigEntryAuthFailed("VehicleManager not created")

        _LOGGER.info("Checking/refreshing token...")
        await self.vehicle_manager.check_and_refresh_token()

        _LOGGER.info("Initializing vehicles...")
        await self.vehicle_manager.initialize()

        _LOGGER.info(
            "Found %d vehicles",
            len(self.vehicle_manager.vehicles) if self.vehicle_manager.vehicles else 0
        )

    async def async_step_otp_method(self, user_input: dict[str, Any] | None = None):
        """Handle OTP delivery method selection."""
        _LOGGER.debug(f"OTP method step with input: {user_input}")

        errors: dict[str, str] = {}

        # Build options based on what's available
        otp_options = {}
        description_parts = []

        if self._otp_has_email and self._otp_email:
            otp_options["EMAIL"] = f"Email ({self._otp_email})"
            description_parts.append(f"Email: {self._otp_email}")
        if self._otp_has_phone and self._otp_phone:
            otp_options["PHONE"] = f"Phone/SMS ({self._otp_phone})"
            description_parts.append(f"Phone: {self._otp_phone}")

        # Fallback if detection didn't work yet
        if not otp_options:
            otp_options = {
                "EMAIL": "Email",
                "PHONE": "Phone/SMS",
            }
            description_parts = ["Select how to receive your OTP code"]

        description = "Choose where to send the OTP code:\n" + "\n".join(description_parts)

        data_schema = vol.Schema({
            vol.Required(CONF_OTP_METHOD): vol.In(otp_options),
        })

        if user_input is not None:
            # Store the selected method
            self._otp_method = user_input[CONF_OTP_METHOD]
            _LOGGER.info(f"User selected OTP delivery: {self._otp_method}")

            # Proceed to OTP code entry
            return await self.async_step_otp_code()

        return self.async_show_form(
            step_id="otp_method",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"description": description},
        )

    async def async_step_otp_code(self, user_input: dict[str, Any] | None = None):
        """Handle OTP code entry."""
        _LOGGER.debug(f"OTP code step with input: {user_input}")

        data_schema = vol.Schema({
            vol.Required(CONF_OTP_CODE): str,
        })
        errors: dict[str, str] = {}

        if user_input is not None:
            # Store OTP code for the handler
            self.data[CONF_OTP_CODE] = user_input[CONF_OTP_CODE]

            try:
                # Wait for the initialization task to complete
                _LOGGER.info("Waiting for VehicleManager initialization to complete...")
                await asyncio.wait_for(self.otp_task, timeout=180)

                if self.vehicle_manager is None or not self.vehicle_manager.vehicles:
                    _LOGGER.error("No vehicles found after initialization")
                    errors["base"] = "no_vehicles"
                else:
                    # Build vehicles list for the next step
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

            except asyncio.TimeoutError:
                _LOGGER.error("Timeout waiting for initialization")
                errors["base"] = "timeout"
            except ConfigEntryAuthFailed as e:
                _LOGGER.error(f"Auth failed: {e}")
                errors["base"] = "auth"
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
