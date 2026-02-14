"""Vehicle Coordinator for Kia/Hyundai/Genesis US integration.

This coordinator manages data updates and API interactions using the
embedded API libraries for Kia, Hyundai, and Genesis.
"""

from __future__ import annotations

from asyncio import sleep
from datetime import timedelta, datetime
from logging import getLogger
from typing import Any

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util
from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    REQUEST_REFRESH_DEFAULT_COOLDOWN,
)

from .kia_hyundai_api import UsKia
from .kia_hyundai_api.us_hyundai import UsHyundai
from .kia_hyundai_api.us_genesis import UsGenesis
from .const import (
    DOMAIN,
    DELAY_BETWEEN_ACTION_IN_PROGRESS_CHECKING,
    TEMPERATURE_MAX,
    TEMPERATURE_MIN,
    SeatSettings,
)
from .util import safely_get_json_value, convert_last_updated_str_to_datetime

_LOGGER = getLogger(__name__)

# Type alias for all supported API clients
ApiConnection = UsKia | UsHyundai | UsGenesis


class VehicleCoordinator(DataUpdateCoordinator):
    """Coordinator for Kia/Hyundai vehicle data updates."""

    # Desired climate settings (set by UI before starting climate)
    climate_desired_defrost: bool = False
    climate_desired_heating_acc: bool = False
    desired_temperature: int = 72  # Default temperature in Fahrenheit
    desired_steering_wheel_heat: int = 0  # 0=off, 1=low/on, 2=high
    desired_driver_seat_comfort: SeatSettings | None = None
    desired_passenger_seat_comfort: SeatSettings | None = None
    desired_left_rear_seat_comfort: SeatSettings | None = None
    desired_right_rear_seat_comfort: SeatSettings | None = None

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        vehicle_id: str,
        vehicle_name: str,
        vehicle_model: str,
        api_connection: ApiConnection,
        scan_interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        self.vehicle_id: str = vehicle_id
        self.vehicle_name: str = vehicle_name
        self.vehicle_model: str = vehicle_model
        self.api_connection: ApiConnection = api_connection

        request_refresh_debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=REQUEST_REFRESH_DEFAULT_COOLDOWN,
            immediate=False,
        )

        async def refresh() -> dict[str, Any]:
            """Refresh vehicle data from the API."""
            # Wait for any pending actions to complete
            while self.last_action_name is not None:
                try:
                    finished = await self.api_connection.check_last_action_finished(
                        vehicle_id=vehicle_id
                    )
                    if finished:
                        break
                except ClientError as err:
                    _LOGGER.error("Error checking action status: %s", err)
                    break

                _LOGGER.debug("Waiting for action to complete")
                await sleep(DELAY_BETWEEN_ACTION_IN_PROGRESS_CHECKING)

            # Get cached vehicle status - handle temporary API errors gracefully
            try:
                new_data = await self.api_connection.get_cached_vehicle_status(
                    vehicle_id=vehicle_id
                )
            except ClientError as err:
                # API temporarily unavailable (common after remote commands)
                # Return existing data if available to prevent going unavailable
                if self.data is not None:
                    _LOGGER.warning(
                        "Temporary API error during refresh, using cached data: %s", err
                    )
                    return self.data
                else:
                    # No cached data available, must raise the error
                    raise

            # Sort target SOC by plug type if present
            target_soc = safely_get_json_value(
                new_data,
                "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.targetSOC"
            )
            if target_soc is not None:
                target_soc.sort(key=lambda x: x["plugType"])

            new_data["last_action_status"] = self.api_connection.last_action
            return new_data

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}-{self.vehicle_name}",
            update_interval=scan_interval,
            update_method=refresh,
            request_refresh_debouncer=request_refresh_debouncer,
            always_update=False,
        )

    @property
    def id(self) -> str:
        """Return vehicle id."""
        return self.vehicle_id

    @property
    def can_remote_lock(self) -> bool:
        """Return if remote lock is available."""
        return safely_get_json_value(
            self.data,
            "vehicleConfig.vehicleFeature.remoteFeature.lock",
            bool
        )

    @property
    def doors_locked(self) -> bool:
        """Return if doors are locked."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.doorLock",
            bool
        )

    @property
    def last_action_name(self) -> str | None:
        """Return name of last action in progress."""
        if self.api_connection.last_action is not None:
            return self.api_connection.last_action.get("name")
        return None

    @property
    def latitude(self) -> float | None:
        """Return vehicle latitude."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.location.coord.lat",
            float
        )

    @property
    def longitude(self) -> float | None:
        """Return vehicle longitude."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.location.coord.lon",
            float
        )

    @property
    def is_ev(self) -> bool:
        """Return True if this is an electric vehicle."""
        ev_status = safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus"
        )
        return ev_status is not None

    @property
    def ev_battery_level(self) -> int | None:
        """Return EV battery percentage."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.batteryStatus",
            int
        )

    @property
    def odometer_value(self) -> float | None:
        """Return odometer reading."""
        return safely_get_json_value(
            self.data,
            "vehicleConfig.vehicleDetail.vehicle.mileage",
            int
        )

    @property
    def car_battery_level(self) -> int | None:
        """Return 12V battery percentage."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.batteryStatus.stateOfCharge",
            int
        )

    @property
    def last_synced_to_cloud(self) -> datetime | None:
        """Return when vehicle last synced to cloud."""
        last_updated_str = safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.syncDate.utc"
        )
        if last_updated_str:
            return convert_last_updated_str_to_datetime(
                last_updated_str=last_updated_str,
                timezone_of_str=dt_util.UTC,
            )
        return None

    @property
    def last_synced_from_cloud(self) -> datetime | None:
        """Return when data was last fetched from cloud."""
        last_updated_str = safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.dateTime.utc"
        )
        if last_updated_str:
            return convert_last_updated_str_to_datetime(
                last_updated_str=last_updated_str,
                timezone_of_str=dt_util.UTC,
            )
        return None

    @property
    def next_service_mile_value(self) -> float | None:
        """Return miles until next service."""
        return safely_get_json_value(
            self.data,
            "vehicleConfig.maintenance.nextServiceMile",
            float
        )

    @property
    def can_remote_climate(self) -> bool:
        """Return if remote climate is available."""
        return safely_get_json_value(
            self.data,
            "vehicleConfig.vehicleFeature.remoteFeature.start",
            bool
        )

    @property
    def climate_hvac_on(self) -> bool:
        """Return if HVAC is on."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.airCtrl",
            bool
        )

    @property
    def climate_temperature_value(self) -> int | None:
        """Return set climate temperature."""
        temperature = safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.airTemp.value",
        )
        if temperature == "LOW":
            return TEMPERATURE_MIN
        if temperature == "HIGH":
            return TEMPERATURE_MAX
        if temperature is not None:
            try:
                temperature = int(temperature)
            except (ValueError, TypeError):
                temperature = 72  # Default
        return temperature

    @property
    def climate_defrost_on(self) -> bool:
        """Return if defrost is on."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.defrost",
            bool
        )

    @property
    def climate_heated_rear_window_on(self) -> bool:
        """Return if rear window heater is on."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatingAccessory.rearWindow",
            bool
        )

    @property
    def climate_heated_side_mirror_on(self) -> bool:
        """Return if side mirror heater is on."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatingAccessory.sideMirror",
            bool
        )

    @property
    def climate_heated_steering_wheel_on(self) -> bool:
        """Return if steering wheel heater is on."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatingAccessory.steeringWheel",
            bool
        )

    @property
    def has_heated_steering_wheel(self) -> bool:
        """Return if vehicle has heated steering wheel."""
        return safely_get_json_value(
            self.data,
            "vehicleConfig.vehicleFeature.remoteFeature.heatedSteeringWheel",
            bool,
        )

    @property
    def climate_steering_wheel_step(self) -> int:
        """Return current steering wheel heat step (0=off, 1=low, 2=high)."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatingAccessory.steeringWheelStep",
            int,
        ) or 0

    @property
    def door_hood_open(self) -> bool:
        """Return if hood is open."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.doorStatus.hood",
            bool
        )

    @property
    def door_trunk_open(self) -> bool:
        """Return if trunk is open."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.doorStatus.trunk",
            bool
        )

    @property
    def door_front_left_open(self) -> bool:
        """Return if front left door is open."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.doorStatus.frontLeft",
            bool
        )

    @property
    def door_front_right_open(self) -> bool:
        """Return if front right door is open."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.doorStatus.frontRight",
            bool
        )

    @property
    def door_back_left_open(self) -> bool:
        """Return if back left door is open."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.doorStatus.backLeft",
            bool
        )

    @property
    def door_back_right_open(self) -> bool:
        """Return if back right door is open."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.doorStatus.backRight",
            bool
        )

    @property
    def engine_on(self) -> bool:
        """Return if engine is running."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.engine",
            bool
        )

    @property
    def tire_all_on(self) -> bool:
        """Return if all tire pressure warning is on."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.tirePressure.all",
            bool
        )

    @property
    def low_fuel_light_on(self) -> bool:
        """Return if low fuel light is on."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.lowFuelLight",
            bool
        )

    @property
    def fuel_level(self) -> float | None:
        """Return fuel level percentage."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.fuelLevel",
            float
        )

    @property
    def ev_battery_charging(self) -> bool:
        """Return if EV battery is charging."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.batteryCharge",
            bool
        )

    @property
    def ev_battery_preconditioning(self) -> bool | None:
        """Return if EV battery preconditioning is active."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.batteryPrecondition",
            bool
        )

    @property
    def ev_plugged_in(self) -> bool:
        """Return if EV is plugged in."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.batteryPlugin",
            bool
        )

    @property
    def ev_charge_limits_ac(self) -> int | None:
        """Return AC charge limit percentage."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.targetSOC.1.targetSOClevel",
            int
        )

    @property
    def ev_charge_limits_dc(self) -> int | None:
        """Return DC charge limit percentage."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.targetSOC.0.targetSOClevel",
            int
        )

    @property
    def ev_charge_current_remaining_duration(self) -> int | None:
        """Return estimated charge time remaining in minutes."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.remainChargeTime.0.timeInterval.value",
            int
        )

    @property
    def ev_remaining_range_value(self) -> int | None:
        """Return estimated EV range in miles."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.drvDistance.0.rangeByFuel.evModeRange.value",
            int
        )

    @property
    def fuel_remaining_range_value(self) -> int | None:
        """Return estimated fuel range in miles."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.drvDistance.0.rangeByFuel.gasModeRange.value",
            int
        ) or safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.distanceToEmpty.value",
            int
        )

    @property
    def total_remaining_range_value(self) -> int | None:
        """Return total estimated range in miles."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.drvDistance.0.rangeByFuel.totalAvailableRange.value",
            int
        ) or safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.distanceToEmpty.value",
            int
        )

    @property
    def has_climate_seats(self) -> bool:
        """Return true if heated or cooled seats installed."""
        heated = safely_get_json_value(
            self.data,
            "vehicleConfig.vehicleFeature.remoteFeature.heatedSeat",
            bool,
        )
        vented = safely_get_json_value(
            self.data,
            "vehicleConfig.vehicleFeature.remoteFeature.ventSeat",
            bool,
        )
        _LOGGER.debug(
            "Vehicle %s has_climate_seats: heatedSeat=%s, ventSeat=%s, result=%s",
            self.vehicle_name, heated, vented, bool(heated or vented)
        )
        return bool(heated or vented)

    @property
    def front_seat_options(self) -> dict:
        """Return front seat options."""
        options = safely_get_json_value(
            self.data,
            "vehicleConfig.heatVentSeat.driverSeat",
            dict,
        ) or {}
        _LOGGER.debug("Vehicle %s front_seat_options: %s", self.vehicle_name, options)
        return options

    @property
    def rear_seat_options(self) -> dict:
        """Return rear seat options."""
        options = safely_get_json_value(
            self.data,
            "vehicleConfig.heatVentSeat.rearLeftSeat",
            dict,
        ) or {}
        _LOGGER.debug("Vehicle %s rear_seat_options: %s", self.vehicle_name, options)
        return options

    @property
    def climate_driver_seat(self) -> tuple:
        """Get the status of the left front seat."""
        seat_data = safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatVentSeat.driverSeat",
            dict,
        )
        if seat_data:
            return tuple(seat_data.values())
        return (0, 1)  # Default: off

    @property
    def climate_passenger_seat(self) -> tuple:
        """Get the status of the right front seat."""
        seat_data = safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatVentSeat.passengerSeat",
            dict,
        )
        if seat_data:
            return tuple(seat_data.values())
        return (0, 1)  # Default: off

    @property
    def climate_left_rear_seat(self) -> tuple:
        """Get the status of the left rear seat."""
        seat_data = safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatVentSeat.rearLeftSeat",
            dict,
        )
        if seat_data:
            return tuple(seat_data.values())
        return (0, 1)  # Default: off

    @property
    def climate_right_rear_seat(self) -> tuple:
        """Get the status of the right rear seat."""
        seat_data = safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatVentSeat.rearRightSeat",
            dict,
        )
        if seat_data:
            return tuple(seat_data.values())
        return (0, 1)  # Default: off

    @property
    def steering_wheel_heat_supported(self) -> bool:
        """Return true if heated steering wheel is supported."""
        return safely_get_json_value(
            self.data,
            "vehicleConfig.vehicleFeature.remoteFeature.heatedSteeringWheel",
            bool,
        )

    @property
    def steering_wheel_heat_step_level(self) -> int:
        """Return steering wheel heat step level (1=on/off, 2=off/low/high)."""
        level = safely_get_json_value(
            self.data,
            "vehicleConfig.vehicleFeature.remoteFeature.steeringWheelStepLevel",
            int,
        )
        # Default to 2 (off/low/high) if not specified but steering wheel is supported
        return level if level else 2

    @property
    def climate_steering_wheel(self) -> int:
        """Return current steering wheel heat level (0=off, 1=low/on, 2=high)."""
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatingAccessory.steeringWheel",
            int,
        ) or 0
