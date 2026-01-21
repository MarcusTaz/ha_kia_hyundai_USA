"""API Adapter for EU library (hyundai-kia-connect-api).

This module bridges the EU library's VehicleManager to the existing
US integration's coordinator interface, allowing us to use the working
EU library auth/API while keeping all existing sensors and entities intact.
"""

from __future__ import annotations

import logging
from typing import Any

from hyundai_kia_connect_api import VehicleManager, Vehicle
from hyundai_kia_connect_api.ApiImpl import ClimateRequestOptions
from hyundai_kia_connect_api.const import ORDER_STATUS

from .const import (
    REGION_USA,
    SeatSettings,
)

_LOGGER = logging.getLogger(__name__)


class EUApiAdapter:
    """Adapter that wraps EU library's VehicleManager for US integration compatibility.

    This adapter provides a consistent interface that matches what the existing
    US integration coordinator expects, while using the EU library under the hood.
    """

    def __init__(
        self,
        vehicle_manager: VehicleManager,
        vehicle_id: str,
    ) -> None:
        """Initialize the adapter.

        Args:
            vehicle_manager: The EU library VehicleManager instance
            vehicle_id: The ID of the specific vehicle this adapter manages
        """
        self._manager = vehicle_manager
        self._vehicle_id = vehicle_id
        self._last_action: dict[str, Any] | None = None

    @property
    def vehicle_manager(self) -> VehicleManager:
        """Return the underlying VehicleManager."""
        return self._manager

    @property
    def vehicle(self) -> Vehicle:
        """Return the Vehicle object from the manager."""
        return self._manager.get_vehicle(self._vehicle_id)

    @property
    def last_action(self) -> dict[str, Any] | None:
        """Return the last action status (for compatibility)."""
        return self._last_action

    async def get_cached_vehicle_status(self, vehicle_id: str) -> dict[str, Any]:
        """Get cached vehicle status, formatted for US integration compatibility.

        This method fetches the latest cached state from the EU library and
        transforms it into a format compatible with the existing US integration
        data access patterns (using dot-notation paths).
        """
        await self._manager.check_and_refresh_token()
        await self._manager.update_vehicle_with_cached_state(vehicle_id)
        vehicle = self._manager.get_vehicle(vehicle_id)

        # Build a nested dict structure that matches US integration's expected paths
        # The US integration uses safely_get_json_value with paths like:
        # "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.evStatus.batteryStatus"
        return self._build_compatible_data_structure(vehicle)

    def _build_compatible_data_structure(self, vehicle: Vehicle) -> dict[str, Any]:
        """Build a data structure compatible with US integration's JSON path access.

        The US integration uses safely_get_json_value() to access data via
        dot-notation paths. This method creates a nested dict that matches
        those expected paths.
        """
        # Get seat status in the expected format (mode, level) tuple
        front_left_seat = self._parse_seat_status(vehicle.front_left_seat_status)
        front_right_seat = self._parse_seat_status(vehicle.front_right_seat_status)
        rear_left_seat = self._parse_seat_status(vehicle.rear_left_seat_status)
        rear_right_seat = self._parse_seat_status(vehicle.rear_right_seat_status)

        # Build the nested structure matching US integration paths
        data = {
            "vehicleConfig": {
                "vehicleDetail": {
                    "vehicle": {
                        "mileage": vehicle.odometer,
                    }
                },
                "vehicleFeature": {
                    "remoteFeature": {
                        "lock": True,  # Assume remote lock is available
                        "start": True,  # Assume remote start is available
                        "heatedSeat": front_left_seat is not None,
                        "ventSeat": front_left_seat is not None,
                    }
                },
                "maintenance": {
                    "nextServiceMile": vehicle.next_service_distance,
                },
                "heatVentSeat": {
                    "driverSeat": {
                        "heatVentType": 1 if front_left_seat else 0,
                    },
                    "rearLeftSeat": {
                        "heatVentType": 1 if rear_left_seat else 0,
                    },
                },
            },
            "lastVehicleInfo": {
                "location": {
                    "coord": {
                        "lat": vehicle.location_latitude,
                        "lon": vehicle.location_longitude,
                    }
                },
                "vehicleStatusRpt": {
                    "vehicleStatus": {
                        "syncDate": {
                            "utc": self._format_datetime_for_us(vehicle.last_updated_at),
                        },
                        "dateTime": {
                            "utc": self._format_datetime_for_us(vehicle.last_updated_at),
                        },
                        "doorLock": vehicle.is_locked,
                        "doorStatus": {
                            "hood": vehicle.hood_is_open,
                            "trunk": vehicle.trunk_is_open,
                            "frontLeft": vehicle.front_left_door_is_open,
                            "frontRight": vehicle.front_right_door_is_open,
                            "backLeft": vehicle.back_left_door_is_open,
                            "backRight": vehicle.back_right_door_is_open,
                        },
                        "engine": vehicle.engine_is_running,
                        "lowFuelLight": vehicle.fuel_level_is_low,
                        "fuelLevel": vehicle.fuel_level,
                        "batteryStatus": {
                            "stateOfCharge": vehicle.car_battery_percentage,
                        },
                        "tirePressure": {
                            "all": vehicle.tire_pressure_all_warning_is_on,
                        },
                        "distanceToEmpty": {
                            "value": vehicle.fuel_driving_range,
                        },
                        "climate": {
                            "airCtrl": vehicle.air_control_is_on,
                            "airTemp": {
                                "value": self._get_climate_temp(vehicle),
                            },
                            "defrost": vehicle.defrost_is_on,
                            "heatingAccessory": {
                                "rearWindow": vehicle.back_window_heater_is_on,
                                "sideMirror": vehicle.side_mirror_heater_is_on,
                                "steeringWheel": vehicle.steering_wheel_heater_is_on,
                            },
                            "heatVentSeat": {
                                "driverSeat": front_left_seat,
                                "passengerSeat": front_right_seat,
                                "rearLeftSeat": rear_left_seat,
                                "rearRightSeat": rear_right_seat,
                            },
                        },
                        "evStatus": {
                            "batteryStatus": vehicle.ev_battery_percentage,
                            "batteryCharge": vehicle.ev_battery_is_charging,
                            "batteryPlugin": vehicle.ev_battery_is_plugged_in,
                            "targetSOC": self._build_target_soc(vehicle),
                            "remainChargeTime": [
                                {
                                    "timeInterval": {
                                        "value": vehicle.ev_estimated_current_charge_duration,
                                    }
                                }
                            ],
                            "drvDistance": [
                                {
                                    "rangeByFuel": {
                                        "evModeRange": {
                                            "value": vehicle.ev_driving_range,
                                        },
                                        "gasModeRange": {
                                            "value": vehicle.fuel_driving_range,
                                        },
                                        "totalAvailableRange": {
                                            "value": vehicle.total_driving_range,
                                        },
                                    }
                                }
                            ],
                        },
                    }
                },
            },
        }
        return data

    def _parse_seat_status(self, seat_status: Any) -> dict[str, int] | None:
        """Parse EU library seat status to US format.

        EU library uses integer values directly.
        US integration expects a dict that becomes a tuple of (mode, level).

        Returns dict with mode (0=off, 1=heat, 2=cool) and level (1-4).
        """
        if seat_status is None:
            return None

        # EU library returns an integer:
        # 0 = off
        # 1-3 = heat levels (low, medium, high)
        # -1 to -3 = cool levels
        try:
            status = int(seat_status) if seat_status else 0
        except (ValueError, TypeError):
            status = 0

        if status == 0:
            return {"heatVentType": 0, "heatVentLevel": 1}
        elif status > 0:
            # Heating: map 1-3 to level 2-4 (matching US format)
            return {"heatVentType": 1, "heatVentLevel": min(status + 1, 4)}
        else:
            # Cooling: map -1 to -3 to level 2-4
            return {"heatVentType": 2, "heatVentLevel": min(abs(status) + 1, 4)}

    def _format_datetime_for_us(self, dt) -> str | None:
        """Format datetime for US integration (YYYYMMDDHHMMSS)."""
        if dt is None:
            return None
        try:
            return dt.strftime("%Y%m%d%H%M%S")
        except (AttributeError, ValueError):
            return None

    def _get_climate_temp(self, vehicle: Vehicle) -> str | None:
        """Get climate temperature in a format the US integration expects."""
        # The US integration expects string values like "72" or "LOW"/"HIGH"
        # For now, return a default since EU library may not have this
        return "72"

    def _build_target_soc(self, vehicle: Vehicle) -> list[dict]:
        """Build target SOC array matching US format."""
        return [
            {
                "plugType": 0,  # DC fast charging
                "targetSOClevel": vehicle.ev_charge_limits_dc,
            },
            {
                "plugType": 1,  # AC charging
                "targetSOClevel": vehicle.ev_charge_limits_ac,
            },
        ]

    async def check_last_action_finished(self, vehicle_id: str) -> None:
        """Check if the last action has finished.

        For the EU library, we track action status differently.
        """
        if self._last_action is None:
            return

        action_id = self._last_action.get("xid")
        if action_id:
            try:
                status = await self._manager.check_action_status(
                    vehicle_id=vehicle_id,
                    action_id=action_id,
                    synchronous=False,
                )
                if status in (ORDER_STATUS.FINISHED, ORDER_STATUS.FAILED):
                    self._last_action = None
            except Exception as err:
                _LOGGER.warning("Error checking action status: %s", err)
                # Clear action on error to prevent stuck state
                self._last_action = None

    async def lock(self, vehicle_id: str) -> None:
        """Lock the vehicle."""
        _LOGGER.debug("Locking vehicle %s", vehicle_id)
        action_id = await self._manager.lock(vehicle_id)
        self._last_action = {"name": "lock", "xid": action_id}

    async def unlock(self, vehicle_id: str) -> None:
        """Unlock the vehicle."""
        _LOGGER.debug("Unlocking vehicle %s", vehicle_id)
        action_id = await self._manager.unlock(vehicle_id)
        self._last_action = {"name": "unlock", "xid": action_id}

    async def start_climate(
        self,
        vehicle_id: str,
        climate: bool = True,
        set_temp: int | None = None,
        defrost: bool = False,
        heating: bool = False,
        driver_seat: SeatSettings | None = None,
        passenger_seat: SeatSettings | None = None,
        left_rear_seat: SeatSettings | None = None,
        right_rear_seat: SeatSettings | None = None,
    ) -> None:
        """Start climate control."""
        _LOGGER.debug(
            "Starting climate for vehicle %s: temp=%s, defrost=%s, heating=%s",
            vehicle_id, set_temp, defrost, heating
        )

        # Convert Fahrenheit to Celsius for EU library (it expects Celsius)
        temp_celsius = None
        if set_temp is not None:
            temp_celsius = (set_temp - 32) * 5 / 9

        options = ClimateRequestOptions(
            set_temp=temp_celsius,
            climate=climate,
            defrost=defrost,
            heating=1 if heating else 0,
            front_left_seat=int(driver_seat) if driver_seat else None,
            front_right_seat=int(passenger_seat) if passenger_seat else None,
            rear_left_seat=int(left_rear_seat) if left_rear_seat else None,
            rear_right_seat=int(right_rear_seat) if right_rear_seat else None,
        )

        action_id = await self._manager.start_climate(vehicle_id, options)
        self._last_action = {"name": "start_climate", "xid": action_id}

    async def stop_climate(self, vehicle_id: str) -> None:
        """Stop climate control."""
        _LOGGER.debug("Stopping climate for vehicle %s", vehicle_id)
        action_id = await self._manager.stop_climate(vehicle_id)
        self._last_action = {"name": "stop_climate", "xid": action_id}

    async def start_charge(self, vehicle_id: str) -> None:
        """Start charging."""
        _LOGGER.debug("Starting charge for vehicle %s", vehicle_id)
        action_id = await self._manager.start_charge(vehicle_id)
        self._last_action = {"name": "start_charge", "xid": action_id}

    async def stop_charge(self, vehicle_id: str) -> None:
        """Stop charging."""
        _LOGGER.debug("Stopping charge for vehicle %s", vehicle_id)
        action_id = await self._manager.stop_charge(vehicle_id)
        self._last_action = {"name": "stop_charge", "xid": action_id}

    async def set_charge_limits(
        self, vehicle_id: str, ac_limit: int, dc_limit: int
    ) -> None:
        """Set charging limits."""
        _LOGGER.debug(
            "Setting charge limits for vehicle %s: AC=%d, DC=%d",
            vehicle_id, ac_limit, dc_limit
        )
        action_id = await self._manager.set_charge_limits(
            vehicle_id, ac=ac_limit, dc=dc_limit
        )
        self._last_action = {"name": "set_charge_limits", "xid": action_id}

    async def force_refresh_vehicle_state(self, vehicle_id: str) -> None:
        """Force a refresh of vehicle state from the car."""
        _LOGGER.debug("Force refreshing vehicle state for %s", vehicle_id)
        await self._manager.force_refresh_vehicle_state(vehicle_id)
        self._last_action = {"name": "force_refresh", "xid": None}

    async def request_vehicle_data_sync(self, vehicle_id: str) -> None:
        """Request vehicle to sync data (wake up the car).

        This is an alias for force_refresh_vehicle_state to maintain
        compatibility with the US integration's API interface.
        """
        await self.force_refresh_vehicle_state(vehicle_id)

    async def close(self) -> None:
        """Close the API connection (no-op for EU library)."""
        # EU library doesn't require explicit cleanup
        pass


async def create_vehicle_manager(
    username: str,
    password: str,
    brand: int,
    pin: str = "",
    otp_handler=None,
) -> VehicleManager:
    """Create and initialize a VehicleManager instance.

    Args:
        username: Account username/email
        password: Account password
        brand: Brand code (1=Kia, 2=Hyundai, 3=Genesis)
        pin: Account PIN (required for some operations)
        otp_handler: Optional callback for OTP handling

    Returns:
        Initialized VehicleManager instance
    """
    _LOGGER.info(
        "Creating VehicleManager for region=USA, brand=%d, username=%s",
        brand, username
    )

    manager = VehicleManager(
        region=REGION_USA,
        brand=brand,
        username=username,
        password=password,
        pin=pin,
        otp_handler=otp_handler,
    )

    return manager
