from asyncio import sleep
from datetime import timedelta, datetime
from logging import getLogger

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util
from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, REQUEST_REFRESH_DEFAULT_COOLDOWN
from kia_hyundai_api import UsKia

from custom_components.ha_kia_hyundai import DOMAIN
from custom_components.ha_kia_hyundai.const import (
    DELAY_BETWEEN_ACTION_IN_PROGRESS_CHECKING,
    TEMPERATURE_MAX,
    TEMPERATURE_MIN
)
from custom_components.ha_kia_hyundai.util import safely_get_json_value, convert_last_updated_str_to_datetime
from kia_hyundai_api.const import SeatSettings

_LOGGER = getLogger(__name__)


class VehicleCoordinator(DataUpdateCoordinator):
    """Kia Us device object."""

    climate_desired_defrost: bool = False
    climate_desired_heating_acc: bool = False
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
            api_connection: UsKia,
            scan_interval: timedelta,
    ) -> None:
        """Initialize the device."""
        self.vehicle_id: str = vehicle_id
        self.vehicle_name: str = vehicle_name
        self.vehicle_model: str = vehicle_model
        self.api_connection: UsKia = api_connection
        request_refresh_debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=REQUEST_REFRESH_DEFAULT_COOLDOWN,
            immediate=False,
        )

        async def refresh() -> dict[str, any]:
            while self.last_action_name is not None:
                try:
                    await self.api_connection.check_last_action_finished(vehicle_id=vehicle_id)
                except ClientError as err:
                    _LOGGER.error(err)
                if self.last_action_name is not None:
                    _LOGGER.debug(
                        f"requesting another update due to in progress action {self.api_connection.last_action}"
                    )
                    await sleep(DELAY_BETWEEN_ACTION_IN_PROGRESS_CHECKING)
                else:
                    _LOGGER.debug(f"action finished! {self.api_connection.last_action}")
            new_data = await self.api_connection.get_cached_vehicle_status(vehicle_id=vehicle_id)
            target_soc = safely_get_json_value(new_data, "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.targetSOC")
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
            always_update=False
        )

    @property
    def id(self) -> str:
        """Return kia vehicle id."""
        return self.vehicle_id

    @property
    def can_remote_lock(self) -> bool:
        return safely_get_json_value(self.data, "vehicleConfig.vehicleFeature.remoteFeature.lock", bool)

    @property
    def doors_locked(self) -> bool:
        return safely_get_json_value(self.data, "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.doorLock", bool)

    @property
    def last_action_name(self) -> str:
        if self.api_connection.last_action is not None:
            return self.api_connection.last_action["name"]

    @property
    def latitude(self) -> float:
        return safely_get_json_value(self.data, "lastVehicleInfo.location.coord.lat", float)

    @property
    def longitude(self) -> float:
        return safely_get_json_value(self.data, "lastVehicleInfo.location.coord.lon", float)

    @property
    def ev_battery_level(self) -> float:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.batteryStatus",
            int
        )

    @property
    def odometer_value(self) -> float:
        return safely_get_json_value(self.data, "vehicleConfig.vehicleDetail.vehicle.mileage", int)

    @property
    def car_battery_level(self) -> int:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.batteryStatus.stateOfCharge",
            int
        )

    @property
    def last_synced_to_cloud(self) -> datetime:
        return convert_last_updated_str_to_datetime(
            last_updated_str=safely_get_json_value(
                self.data,
                "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.syncDate.utc"
            ),
            timezone_of_str=dt_util.UTC,
        )

    @property
    def last_synced_from_cloud(self) -> datetime:
        return convert_last_updated_str_to_datetime(
            last_updated_str=safely_get_json_value(
                self.data,
                "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.dateTime.utc"
            ),
            timezone_of_str=dt_util.UTC,
        )

    @property
    def next_service_mile_value(self) -> float:
        return safely_get_json_value(
            self.data,
            "vehicleConfig.maintenance.nextServiceMile",
            float
        )

    @property
    def can_remote_climate(self) -> bool:
        return safely_get_json_value(
            self.data,
            "vehicleConfig.vehicleFeature.remoteFeature.start",
            bool
        )

    @property
    def climate_hvac_on(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.airCtrl",
            bool
        )

    @property
    def climate_temperature_value(self) -> int:
        temperature = safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.airTemp.value",
        )
        if temperature == "LOW":
            return TEMPERATURE_MIN
        if temperature == "HIGH":
            return TEMPERATURE_MAX
        if temperature is not None:
            temperature = int(temperature)
        return temperature

    @property
    def climate_defrost_on(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.defrost",
            bool
        )

    @property
    def climate_heated_rear_window_on(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatingAccessory.rearWindow",
            bool
        )

    @property
    def climate_heated_side_mirror_on(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatingAccessory.sideMirror",
            bool
        )

    @property
    def climate_heated_steering_wheel_on(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatingAccessory.steeringWheel",
            bool
        )

    @property
    def door_hood_open(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.doorStatus.hood",
            bool
        )

    @property
    def door_trunk_open(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.doorStatus.trunk",
            bool
        )

    @property
    def door_front_left_open(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.doorStatus.frontLeft",
            bool
        )

    @property
    def door_front_right_open(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.doorStatus.frontRight",
            bool
        )

    @property
    def door_back_left_open(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.doorStatus.backLeft",
            bool
        )

    @property
    def door_back_right_open(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.doorStatus.backRight",
            bool
        )

    @property
    def engine_on(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.engine",
            bool
        )

    @property
    def tire_all_on(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.tirePressure.all",
            bool
        )

    @property
    def low_fuel_light_on(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.lowFuelLight",
            bool
        )

    @property
    def fuel_level(self) -> float:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.fuelLevel",
            float
        )

    @property
    def ev_battery_charging(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.batteryCharge",
            bool
        )

    @property
    def ev_plugged_in(self) -> bool:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.batteryPlugin",
            bool
        )

    @property
    def ev_charge_limits_ac(self) -> int:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.targetSOC.1.targetSOClevel",
            int
        )

    @property
    def ev_charge_limits_dc(self) -> int:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.targetSOC.0.targetSOClevel",
            int
        )

    @property
    def ev_charge_current_remaining_duration(self) -> int:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.remainChargeTime.0.timeInterval.value",
            int
        )

    @property
    def ev_remaining_range_value(self) -> int:
        return safely_get_json_value(
            self.data,
            "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.drvDistance.0.rangeByFuel.evModeRange.value",
            int
        )

    @property
    def fuel_remaining_range_value(self) -> int:
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
    def total_remaining_range_value(self) -> int:
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
        return safely_get_json_value(
            self.data,
            "vehicleConfig.vehicleFeature.remoteFeature.heatedSeat",
            bool,
        ) or safely_get_json_value(
            self.data,
            "vehicleConfig.vehicleFeature.remoteFeature.ventSeat",
            bool,
        )

    @property
    def front_seat_options(self) -> dict:
        """Return front seat options."""
        return safely_get_json_value(
            self.data,
            "vehicleConfig.heatVentSeat.driverSeat",
            dict,
        )

    @property
    def rear_seat_options(self) -> dict:
        """Return rear seat options."""
        return safely_get_json_value(
            self.data,
            "vehicleConfig.heatVentSeat.rearLeftSeat",
            dict,
        )

    @property
    def climate_driver_seat(self) -> tuple:
        """Get the status of the left front seat."""
        return tuple(
            safely_get_json_value(
                self.data,
                "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatVentSeat.driverSeat",
                dict,
            ).values()
        )

    @property
    def climate_passenger_seat(self) -> tuple:
        """Get the status of the right front seat."""
        return tuple(
            safely_get_json_value(
                self.data,
                "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatVentSeat.passengerSeat",
                dict,
            ).values()
        )

    @property
    def climate_left_rear_seat(self) -> tuple:
        """Get the status of the left rear seat."""
        return tuple(
            safely_get_json_value(
                self.data,
                "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatVentSeat.rearLeftSeat",
                dict,
            ).values()
        )

    @property
    def climate_right_rear_seat(self) -> tuple:
        """Get the status of the right rear seat."""
        return tuple(
            safely_get_json_value(
                self.data,
                "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.climate.heatVentSeat.rearRightSeat",
                dict,
            ).values()
        )
