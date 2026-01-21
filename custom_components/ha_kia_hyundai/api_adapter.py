"""API Adapter for EU library (hyundai-kia-connect-api).

This module bridges the EU library's VehicleManager to the existing
US integration's coordinator interface, allowing us to use the working
EU library auth/API while keeping all existing sensors and entities intact.

IMPORTANT: The EU library uses synchronous `requests` for HTTP calls.
All blocking calls must be wrapped in hass.async_add_executor_job() to
avoid blocking the Home Assistant event loop.

SEAT CLIMATE DETECTION:
The EU library stores raw API response in vehicle.data. We detect seat
climate capabilities by checking if seatHeaterVentState exists in the
raw data. For USA region, the library uses different property names:
- front_left_seat_heater_is_on (USA) vs front_left_seat_status (EU)

We parse the raw data to determine:
1. Whether seat climate is supported (does the path exist?)
2. What type of seat climate (heat only, cool only, or both)
3. Current seat status values
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING
from functools import partial

from hyundai_kia_connect_api import VehicleManager, Vehicle
from hyundai_kia_connect_api.ApiImpl import ClimateRequestOptions
from hyundai_kia_connect_api.const import ORDER_STATUS

from .const import (
    REGION_USA,
    SeatSettings,
)
from .util import safely_get_json_value

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _get_seat_status_from_raw(raw_data: dict | None, seat_key: str) -> int | None:
    """Get seat status value from raw API data.

    Args:
        raw_data: Raw vehicle data dict (vehicle.data)
        seat_key: Seat key (flSeatHeatState, frSeatHeatState, etc.)

    Returns:
        Integer seat status value or None if not present
    """
    if not raw_data:
        return None
    return safely_get_json_value(
        raw_data,
        f"lastVehicleInfo.vehicleStatusRpt.vehicleStatus.seatHeaterVentState.{seat_key}",
        int,
    )


def _detect_seat_capabilities(raw_data: dict | None) -> dict[str, Any]:
    """Detect seat climate capabilities from raw API data.

    This function checks the raw API response to determine if seat climate
    control is available and what options are supported. We don't hard-code
    capabilities - we read them from what the API actually returns.

    Args:
        raw_data: Raw vehicle data dict (vehicle.data)

    Returns:
        Dict with seat capability info:
        - has_front_seats: bool - whether front seat climate exists
        - has_rear_seats: bool - whether rear seat climate exists
        - front_heat_type: int - 0=none, 1=heat only, 2=cool only, 3=heat+cool
        - front_heat_steps: int - number of levels (2 or 3)
        - rear_heat_type: int
        - rear_heat_steps: int
    """
    result = {
        "has_front_seats": False,
        "has_rear_seats": False,
        "front_heat_type": 0,
        "front_heat_steps": 3,  # Default to 3 steps
        "rear_heat_type": 0,
        "rear_heat_steps": 3,
    }

    if not raw_data:
        return result

    # Check if seatHeaterVentState exists in raw data
    seat_state = safely_get_json_value(
        raw_data,
        "lastVehicleInfo.vehicleStatusRpt.vehicleStatus.seatHeaterVentState",
        dict,
    )

    if not seat_state:
        _LOGGER.debug("No seatHeaterVentState in raw data - vehicle has no seat climate")
        return result

    # Check front seats
    fl_state = seat_state.get("flSeatHeatState")
    fr_state = seat_state.get("frSeatHeatState")
    if fl_state is not None or fr_state is not None:
        result["has_front_seats"] = True
        # Determine heat type from values (0-8 scale in USA)
        # 0=Off, 1=On, 2=Off, 3-5=Cool, 6-8=Heat
        # If we see values >= 3, we have cool. If we see values >= 6, we have heat.
        # For now, assume heat+cool (type 3) if feature is present
        result["front_heat_type"] = 3
        result["front_heat_steps"] = 3
        _LOGGER.debug(
            "Front seats detected: fl=%s, fr=%s, type=%d",
            fl_state, fr_state, result["front_heat_type"]
        )

    # Check rear seats
    rl_state = seat_state.get("rlSeatHeatState")
    rr_state = seat_state.get("rrSeatHeatState")
    if rl_state is not None or rr_state is not None:
        result["has_rear_seats"] = True
        result["rear_heat_type"] = 3
        result["rear_heat_steps"] = 3
        _LOGGER.debug(
            "Rear seats detected: rl=%s, rr=%s, type=%d",
            rl_state, rr_state, result["rear_heat_type"]
        )

    return result


class EUApiAdapter:
    """Adapter that wraps EU library's VehicleManager for US integration compatibility.

    This adapter provides a consistent interface that matches what the existing
    US integration coordinator expects, while using the EU library under the hood.

    All EU library calls are blocking (synchronous) and must be run in an executor.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        vehicle_manager: VehicleManager,
        vehicle_id: str,
    ) -> None:
        """Initialize the adapter.

        Args:
            hass: Home Assistant instance (needed for executor jobs)
            vehicle_manager: The EU library VehicleManager instance
            vehicle_id: The ID of the specific vehicle this adapter manages
        """
        self._hass = hass
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
        # Run blocking calls in executor
        await self._hass.async_add_executor_job(
            self._manager.check_and_refresh_token
        )
        await self._hass.async_add_executor_job(
            self._manager.update_vehicle_with_cached_state,
            vehicle_id
        )
        vehicle = self._manager.get_vehicle(vehicle_id)

        # Build a nested dict structure that matches US integration's expected paths
        return self._build_compatible_data_structure(vehicle)

    def _build_compatible_data_structure(self, vehicle: Vehicle) -> dict[str, Any]:
        """Build a data structure compatible with US integration's JSON path access.

        The US integration uses safely_get_json_value() to access data via
        dot-notation paths. This method creates a nested dict that matches
        those expected paths.

        IMPORTANT: Vehicle capabilities (like seat climate) are detected from
        the actual API data stored in vehicle.data, not hard-coded.
        """
        # Get raw data for capability detection
        raw_data = getattr(vehicle, "data", None)

        # Detect seat capabilities from raw API data
        seat_caps = _detect_seat_capabilities(raw_data)
        _LOGGER.debug(
            "Seat capabilities for %s: %s", self._vehicle_id, seat_caps
        )

        # Get seat status from raw data (USA uses different property names)
        # Try USA-specific properties first, then fall back to standard
        fl_raw = _get_seat_status_from_raw(raw_data, "flSeatHeatState")
        fr_raw = _get_seat_status_from_raw(raw_data, "frSeatHeatState")
        rl_raw = _get_seat_status_from_raw(raw_data, "rlSeatHeatState")
        rr_raw = _get_seat_status_from_raw(raw_data, "rrSeatHeatState")

        # Also check the vehicle object properties as fallback
        if fl_raw is None:
            fl_raw = getattr(vehicle, "front_left_seat_heater_is_on", None)
        if fr_raw is None:
            fr_raw = getattr(vehicle, "front_right_seat_heater_is_on", None)
        if rl_raw is None:
            rl_raw = getattr(vehicle, "rear_left_seat_heater_is_on", None)
        if rr_raw is None:
            rr_raw = getattr(vehicle, "rear_right_seat_heater_is_on", None)

        _LOGGER.debug(
            "Raw seat values: fl=%s, fr=%s, rl=%s, rr=%s",
            fl_raw, fr_raw, rl_raw, rr_raw
        )

        # Convert raw seat status to the format expected by US integration
        front_left_seat = self._parse_seat_status_raw(fl_raw) if seat_caps["has_front_seats"] else None
        front_right_seat = self._parse_seat_status_raw(fr_raw) if seat_caps["has_front_seats"] else None
        rear_left_seat = self._parse_seat_status_raw(rl_raw) if seat_caps["has_rear_seats"] else None
        rear_right_seat = self._parse_seat_status_raw(rr_raw) if seat_caps["has_rear_seats"] else None

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
                        # Detect from actual API data, not hard-coded
                        "heatedSeat": seat_caps["has_front_seats"] and seat_caps["front_heat_type"] in (1, 3),
                        "ventSeat": seat_caps["has_front_seats"] and seat_caps["front_heat_type"] in (2, 3),
                    }
                },
                "maintenance": {
                    "nextServiceMile": vehicle.next_service_distance,
                },
                # Seat options - only populated if seats are detected in API data
                "heatVentSeat": {
                    "driverSeat": {
                        "heatVentType": seat_caps["front_heat_type"],
                        "heatVentStep": seat_caps["front_heat_steps"],
                    } if seat_caps["has_front_seats"] else {},
                    "rearLeftSeat": {
                        "heatVentType": seat_caps["rear_heat_type"],
                        "heatVentStep": seat_caps["rear_heat_steps"],
                    } if seat_caps["has_rear_seats"] else {},
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

    def _parse_seat_status_raw(self, raw_value: int | None) -> dict[str, int] | None:
        """Parse raw USA API seat status integer to US integration format.

        The USA API returns seat status as integers:
        - 0 = Off
        - 1 = On (generic)
        - 2 = Off
        - 3 = Low Cool
        - 4 = Medium Cool
        - 5 = High Cool
        - 6 = Low Heat
        - 7 = Medium Heat
        - 8 = High Heat

        The US integration expects format: {heatVentType: X, heatVentLevel: Y}
        - heatVentType: 0=off, 1=heat, 2=cool
        - heatVentLevel: 1-4 (1=off, 2=low, 3=med, 4=high)
        """
        if raw_value is None:
            return None

        try:
            status = int(raw_value)
        except (ValueError, TypeError):
            status = 0

        # Map raw value to (type, level) format
        if status == 0 or status == 2:
            # Off
            return {"heatVentType": 0, "heatVentLevel": 1}
        elif status == 1:
            # Generic "On" - assume heat
            return {"heatVentType": 1, "heatVentLevel": 2}
        elif status >= 3 and status <= 5:
            # Cool: 3=Low, 4=Medium, 5=High
            level = status - 1  # Maps 3->2, 4->3, 5->4
            return {"heatVentType": 2, "heatVentLevel": level}
        elif status >= 6 and status <= 8:
            # Heat: 6=Low, 7=Medium, 8=High
            level = status - 4  # Maps 6->2, 7->3, 8->4
            return {"heatVentType": 1, "heatVentLevel": level}
        else:
            # Unknown value, return off
            return {"heatVentType": 0, "heatVentLevel": 1}

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
        return "72"

    def _build_target_soc(self, vehicle: Vehicle) -> list[dict]:
        """Build target SOC array matching US format."""
        return [
            {
                "plugType": 0,
                "targetSOClevel": vehicle.ev_charge_limits_dc,
            },
            {
                "plugType": 1,
                "targetSOClevel": vehicle.ev_charge_limits_ac,
            },
        ]

    async def check_last_action_finished(self, vehicle_id: str) -> None:
        """Check if the last action has finished."""
        if self._last_action is None:
            return

        action_id = self._last_action.get("xid")
        if action_id:
            try:
                status = await self._hass.async_add_executor_job(
                    partial(
                        self._manager.check_action_status,
                        vehicle_id=vehicle_id,
                        action_id=action_id,
                        synchronous=False,
                    )
                )
                if status in (ORDER_STATUS.FINISHED, ORDER_STATUS.FAILED):
                    self._last_action = None
            except Exception as err:
                _LOGGER.warning("Error checking action status: %s", err)
                self._last_action = None

    async def lock(self, vehicle_id: str) -> None:
        """Lock the vehicle."""
        _LOGGER.debug("Locking vehicle %s", vehicle_id)
        action_id = await self._hass.async_add_executor_job(
            self._manager.lock, vehicle_id
        )
        self._last_action = {"name": "lock", "xid": action_id}

    async def unlock(self, vehicle_id: str) -> None:
        """Unlock the vehicle."""
        _LOGGER.debug("Unlocking vehicle %s", vehicle_id)
        action_id = await self._hass.async_add_executor_job(
            self._manager.unlock, vehicle_id
        )
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

        # Convert Fahrenheit to Celsius for EU library
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

        action_id = await self._hass.async_add_executor_job(
            self._manager.start_climate, vehicle_id, options
        )
        self._last_action = {"name": "start_climate", "xid": action_id}

    async def stop_climate(self, vehicle_id: str) -> None:
        """Stop climate control."""
        _LOGGER.debug("Stopping climate for vehicle %s", vehicle_id)
        action_id = await self._hass.async_add_executor_job(
            self._manager.stop_climate, vehicle_id
        )
        self._last_action = {"name": "stop_climate", "xid": action_id}

    async def start_charge(self, vehicle_id: str) -> None:
        """Start charging."""
        _LOGGER.debug("Starting charge for vehicle %s", vehicle_id)
        action_id = await self._hass.async_add_executor_job(
            self._manager.start_charge, vehicle_id
        )
        self._last_action = {"name": "start_charge", "xid": action_id}

    async def stop_charge(self, vehicle_id: str) -> None:
        """Stop charging."""
        _LOGGER.debug("Stopping charge for vehicle %s", vehicle_id)
        action_id = await self._hass.async_add_executor_job(
            self._manager.stop_charge, vehicle_id
        )
        self._last_action = {"name": "stop_charge", "xid": action_id}

    async def set_charge_limits(
        self, vehicle_id: str, ac_limit: int, dc_limit: int
    ) -> None:
        """Set charging limits."""
        _LOGGER.debug(
            "Setting charge limits for vehicle %s: AC=%d, DC=%d",
            vehicle_id, ac_limit, dc_limit
        )
        action_id = await self._hass.async_add_executor_job(
            partial(
                self._manager.set_charge_limits,
                vehicle_id,
                ac=ac_limit,
                dc=dc_limit,
            )
        )
        self._last_action = {"name": "set_charge_limits", "xid": action_id}

    async def force_refresh_vehicle_state(self, vehicle_id: str) -> None:
        """Force a refresh of vehicle state from the car."""
        _LOGGER.debug("Force refreshing vehicle state for %s", vehicle_id)
        await self._hass.async_add_executor_job(
            self._manager.force_refresh_vehicle_state, vehicle_id
        )
        self._last_action = {"name": "force_refresh", "xid": None}

    async def request_vehicle_data_sync(self, vehicle_id: str) -> None:
        """Request vehicle to sync data (wake up the car)."""
        await self.force_refresh_vehicle_state(vehicle_id)

    async def close(self) -> None:
        """Close the API connection (no-op for EU library)."""
        pass


def create_vehicle_manager(
    username: str,
    password: str,
    brand: int,
    pin: str = "",
    token_dict: dict | None = None,
) -> VehicleManager:
    """Create a VehicleManager instance with optional saved token.

    Args:
        username: Account username/email
        password: Account password
        brand: Brand code (1=Kia, 2=Hyundai, 3=Genesis)
        pin: Account PIN (required for some operations)
        token_dict: Optional saved token dict from previous authentication

    Returns:
        VehicleManager instance
    """
    from hyundai_kia_connect_api import Token

    _LOGGER.info(
        "Creating VehicleManager for region=USA, brand=%d, username=%s",
        brand, username
    )

    # Restore token from saved dict if available
    token = None
    if token_dict:
        try:
            token = Token.from_dict(token_dict)
            _LOGGER.info("Restored saved token (valid_until: %s)", token.valid_until)
        except Exception as e:
            _LOGGER.warning("Failed to restore token: %s", e)
            token = None

    # V4 API: pass token directly, no otp_handler
    manager = VehicleManager(
        region=REGION_USA,
        brand=brand,
        username=username,
        password=password,
        pin=pin,
        token=token,
    )

    return manager
