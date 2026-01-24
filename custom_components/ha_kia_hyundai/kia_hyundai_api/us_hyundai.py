"""UsHyundai - Hyundai BlueLink API for USA.

Based on the EU library's HyundaiBlueLinkApiUSA implementation.
Supports both:
1. Direct login with username/password + PIN (older accounts)
2. OTP authentication if required by the account (newer accounts)

Key differences from Kia:
1. May or may not require OTP depending on account
2. Requires PIN for vehicle commands
3. Different API endpoints and headers
4. Uses registration ID (regid) instead of vinkey
"""

import logging
import asyncio

from datetime import datetime
import ssl
import uuid
import certifi
import time

from functools import partial
from aiohttp import ClientSession, ClientResponse

from .errors import AuthError, ActionAlreadyInProgressError
from .const import (
    HYUNDAI_API_URL_HOST,
    HYUNDAI_LOGIN_API_BASE,
    HYUNDAI_API_URL_BASE,
    SeatSettings,
)
from .util_http import request_with_logging_bluelink, request_with_active_session

_LOGGER = logging.getLogger(__name__)


def _seat_settings_hyundai(level: SeatSettings | None) -> int:
    """Convert seat setting to Hyundai BlueLink API value.
    
    Based on API supportedLevels (typically '2,6,7,8,3,4,5'):
    - 0: Off
    - 1, 2, 3: Heat levels (Low, Medium, High)
    - 6, 7, 8: Cool/Vent levels (Low, Medium, High)
    """
    if level is None:
        return 0
    
    level_value = level.value if hasattr(level, 'value') else level
    _LOGGER.debug("_seat_settings_hyundai: input level=%s, value=%s", level, level_value)
    
    # SeatSettings enum: NONE=0, CoolLow=1, CoolMedium=2, CoolHigh=3, HeatLow=4, HeatMedium=5, HeatHigh=6
    result = 0
    if level_value == 6:  # HeatHigh
        result = 3
    elif level_value == 5:  # HeatMedium
        result = 2
    elif level_value == 4:  # HeatLow
        result = 1
    elif level_value == 3:  # CoolHigh
        result = 8  # API uses 8 for cool high
    elif level_value == 2:  # CoolMedium
        result = 7  # API uses 7 for cool medium
    elif level_value == 1:  # CoolLow
        result = 6  # API uses 6 for cool low
    else:  # NONE (0) or unknown
        result = 0
    
    _LOGGER.debug("_seat_settings_hyundai: output value=%s", result)
    return result


class UsHyundai:
    """Hyundai BlueLink USA API client (PIN-based authentication)."""
    
    _ssl_context = None
    access_token: str | None = None
    refresh_token: str | None = None
    vehicles: list[dict] | None = None
    last_action = None

    def __init__(
            self,
            username: str,
            password: str,
            pin: str,
            device_id: str | None = None,
            client_session: ClientSession | None = None
    ):
        """Initialize Hyundai API client.
        
        Parameters
        ----------
        username : str
            User email address
        password : str
            User password
        pin : str
            BlueLink service PIN (4 digits)
        device_id : str, optional
            Device identifier for API
        """
        self.username = username
        self.password = password
        self.pin = pin
        self.device_id = device_id or str(uuid.uuid4()).upper()
        if client_session is None:
            self.api_session = ClientSession(raise_for_status=False)
        else:
            self.api_session = client_session

    async def get_ssl_context(self):
        if self._ssl_context is None:
            loop = asyncio.get_running_loop()
            new_ssl_context = await loop.run_in_executor(
                None, partial(ssl.create_default_context, cafile=certifi.where())
            )
            await loop.run_in_executor(None, partial(new_ssl_context.load_default_certs))
            new_ssl_context.check_hostname = True
            new_ssl_context.verify_mode = ssl.CERT_REQUIRED
            new_ssl_context.set_ciphers("DEFAULT@SECLEVEL=1")
            new_ssl_context.options = ssl.OP_CIPHER_SERVER_PREFERENCE
            new_ssl_context.options |= 0x4  # SSL_OP_ALLOW_UNSAFE_LEGACY_RENEGOTIATION
            self._ssl_context = new_ssl_context
        return self._ssl_context

    def _api_headers(self) -> dict:
        """Generate API headers for Hyundai BlueLink."""
        ts = time.time()
        utc_offset_hours = int(
            (datetime.fromtimestamp(ts) - datetime.utcfromtimestamp(ts)).total_seconds() / 60 / 60
        )
        
        origin = "https://" + HYUNDAI_API_URL_HOST
        referer = origin + "/login"
        
        headers = {
            "content-type": "application/json;charset=UTF-8",
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.142 Safari/537.36",
            "host": HYUNDAI_API_URL_HOST,
            "origin": origin,
            "referer": referer,
            "from": "SPA",
            "to": "ISS",
            "language": "0",
            "offset": str(utc_offset_hours),
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "refresh": "false",
            "encryptFlag": "false",
            "brandIndicator": "H",
            "client_id": "m66129Bb-em93-SPAHYN-bZ91-am4540zp19920",
            "clientSecret": "v558o935-6nne-423i-baa8",
        }
        return headers

    def _get_authenticated_headers(self) -> dict:
        """Get headers with authentication tokens."""
        headers = self._api_headers()
        headers["username"] = self.username
        headers["accessToken"] = self.access_token or ""
        headers["blueLinkServicePin"] = self.pin
        return headers

    def _get_vehicle_headers(self, vehicle: dict) -> dict:
        """Get headers for vehicle-specific requests."""
        headers = self._get_authenticated_headers()
        headers["registrationId"] = vehicle.get("regid", vehicle.get("id", ""))
        headers["gen"] = str(vehicle.get("generation", vehicle.get("gen", "2")))
        headers["vin"] = vehicle.get("vin", vehicle.get("VIN", ""))
        return headers

    @request_with_logging_bluelink
    async def _post_request_with_logging_and_errors_raised(
            self,
            url: str,
            json_body: dict,
            headers: dict | None = None,
    ) -> ClientResponse:
        if headers is None:
            headers = self._api_headers()
        return await self.api_session.post(
            url=url,
            json=json_body,
            headers=headers,
            ssl=await self.get_ssl_context()
        )

    @request_with_logging_bluelink
    async def _get_request_with_logging_and_errors_raised(
            self,
            url: str,
            headers: dict | None = None,
    ) -> ClientResponse:
        if headers is None:
            headers = self._api_headers()
        return await self.api_session.get(
            url=url,
            headers=headers,
            ssl=await self.get_ssl_context()
        )

    async def login(self):
        """Login to Hyundai BlueLink with username/password (PIN used for commands)."""
        _LOGGER.info("========== HYUNDAI LOGIN START ==========")
        _LOGGER.info("Hyundai login attempt for user: %s", self.username)
        _LOGGER.info("Using API host: %s", HYUNDAI_API_URL_HOST)
        _LOGGER.info("Login URL: %s", HYUNDAI_LOGIN_API_BASE + "oauth/token")
        
        url = HYUNDAI_LOGIN_API_BASE + "oauth/token"
        data = {"username": self.username, "password": self.password}
        
        headers = self._api_headers()
        _LOGGER.info("Request headers (sanitized): brandIndicator=%s, client_id=%s", 
                    headers.get("brandIndicator"), headers.get("client_id"))
        
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body=data,
            headers=headers,
        )
        
        response_json = await response.json()
        _LOGGER.info("Hyundai login response status: %s", response.status)
        _LOGGER.info("Hyundai login response keys: %s", list(response_json.keys()))
        
        # Log specific fields for debugging
        if "access_token" in response_json:
            _LOGGER.info("Response contains access_token: YES (length: %d)", len(response_json.get("access_token", "")))
        else:
            _LOGGER.info("Response contains access_token: NO")
            
        if "errorCode" in response_json:
            _LOGGER.info("Response errorCode: %s", response_json.get("errorCode"))
            _LOGGER.info("Response errorMessage: %s", response_json.get("errorMessage"))
        
        # Check if we got an access token
        if response_json.get("access_token"):
            self.access_token = response_json["access_token"]
            self.refresh_token = response_json.get("refresh_token")
            _LOGGER.info("========== HYUNDAI LOGIN SUCCESS ==========")
            return
        
        # Login failed
        _LOGGER.error("========== HYUNDAI LOGIN FAILED ==========")
        _LOGGER.error("Response: %s", response_json)
        
        error_msg = response_json.get("errorMessage", response_json.get("message", "Unknown error"))
        raise AuthError(f"Hyundai login failed: {error_msg}")

    async def get_vehicles(self):
        """Get list of vehicles for the account."""
        if self.access_token is None:
            await self.login()
        
        url = HYUNDAI_API_URL_BASE + "enrollment/details/" + self.username
        headers = self._get_authenticated_headers()
        
        response = await self._get_request_with_logging_and_errors_raised(
            url=url,
            headers=headers,
        )
        
        response_json = await response.json()
        _LOGGER.debug("Hyundai get_vehicles response: %s", response_json)
        
        self.vehicles = []
        for entry in response_json.get("enrolledVehicleDetails", []):
            vehicle_details = entry.get("vehicleDetails", {})
            vehicle = {
                "id": vehicle_details.get("regid"),
                "regid": vehicle_details.get("regid"),
                "vin": vehicle_details.get("vin"),
                "VIN": vehicle_details.get("vin"),
                "nickName": vehicle_details.get("nickName", ""),
                "modelCode": vehicle_details.get("modelCode", ""),
                "modelYear": vehicle_details.get("modelYear", ""),
                "evStatus": vehicle_details.get("evStatus", "N"),
                "generation": int(vehicle_details.get("vehicleGeneration", "2")),
                "enrollmentStatus": vehicle_details.get("enrollmentStatus", ""),
            }
            if vehicle.get("enrollmentStatus") != "CANCELLED":
                self.vehicles.append(vehicle)
        
        return self.vehicles

    async def find_vehicle(self, vehicle_id: str) -> dict:
        """Find a vehicle by ID."""
        if self.vehicles is None:
            await self.get_vehicles()
        if self.vehicles is None:
            raise ValueError("No vehicles found")
        for vehicle in self.vehicles:
            if vehicle.get("id") == vehicle_id or vehicle.get("regid") == vehicle_id:
                return vehicle
        raise ValueError(f"Vehicle {vehicle_id} not found")

    async def get_cached_vehicle_status(self, vehicle_id: str):
        """Get cached vehicle status from Hyundai API.
        
        Note: Hyundai returns data in a different format than Kia.
        We need to transform it to match our expected format.
        """
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        headers = self._get_vehicle_headers(vehicle)
        
        # Get vehicle status
        url = HYUNDAI_API_URL_BASE + "rcs/rvs/vehicleStatus"
        response = await self._get_request_with_logging_and_errors_raised(
            url=url,
            headers=headers,
        )
        response_json = await response.json()
        _LOGGER.debug("Hyundai vehicle status response: %s", response_json)
        
        # Get vehicle details for additional info
        details_url = HYUNDAI_API_URL_BASE + "enrollment/details/" + self.username
        details_response = await self._get_request_with_logging_and_errors_raised(
            url=details_url,
            headers=self._get_authenticated_headers(),
        )
        details_json = await details_response.json()
        
        # Find this vehicle's details
        vehicle_details = {}
        seat_configs = []
        for entry in details_json.get("enrolledVehicleDetails", []):
            if entry.get("vehicleDetails", {}).get("regid") == vehicle_id:
                vehicle_details = entry.get("vehicleDetails", {})
                seat_configs = vehicle_details.get("seatConfigurations", {}).get("seatConfigs", [])
                break
        
        # Parse seat configurations from API
        # seatLocationID: 1=driver, 2=passenger, 3=rear left, 4=rear right
        seat_config_map = {}
        has_heated_seats = False
        has_ventilated_seats = False
        for seat in seat_configs:
            location_id = seat.get("seatLocationID", "")
            heat_capable = seat.get("heatingCapable", "NO") == "YES"
            vent_capable = seat.get("ventCapable", "NO") == "YES"
            if heat_capable:
                has_heated_seats = True
            if vent_capable:
                has_ventilated_seats = True
            # Determine heatVentType: 0=none, 1=heat only, 2=vent only, 3=heat+vent
            if heat_capable and vent_capable:
                heat_vent_type = 3
            elif heat_capable:
                heat_vent_type = 1
            elif vent_capable:
                heat_vent_type = 2
            else:
                heat_vent_type = 0
            # Parse supported levels to determine step count
            levels = seat.get("supportedLevels", "")
            heat_vent_step = len(levels.split(",")) if levels else 0
            seat_config_map[location_id] = {"heatVentType": heat_vent_type, "heatVentStep": heat_vent_step}
        
        _LOGGER.debug("Hyundai seat configurations from API: %s", seat_config_map)
        
        # Parse vehicle capabilities from API
        steering_wheel_heat_capable = vehicle_details.get("steeringWheelHeatCapable", "NO") == "YES"
        side_mirror_heat_capable = vehicle_details.get("sideMirrorHeatCapable", "NO") == "YES"
        rear_window_heat_capable = vehicle_details.get("rearWindowHeatCapable", "NO") == "YES"
        fatc_available = vehicle_details.get("fatcAvailable", "N") == "Y"  # Remote climate/start
        bluelink_enabled = vehicle_details.get("bluelinkEnabled", False)
        
        _LOGGER.debug(
            "Hyundai vehicle capabilities: steering_heat=%s, mirror_heat=%s, rear_window=%s, fatc=%s, bluelink=%s",
            steering_wheel_heat_capable, side_mirror_heat_capable, rear_window_heat_capable, 
            fatc_available, bluelink_enabled
        )
        
        # Get location
        location = None
        try:
            loc_url = HYUNDAI_API_URL_BASE + "rcs/rfc/findMyCar"
            loc_response = await self._get_request_with_logging_and_errors_raised(
                url=loc_url,
                headers=headers,
            )
            loc_json = await loc_response.json()
            if loc_json.get("coord"):
                location = loc_json
        except Exception as e:
            _LOGGER.debug("Failed to get location: %s", e)
        
        # Transform Hyundai response to match Kia format for compatibility
        vehicle_status = response_json.get("vehicleStatus", {})
        
        # Build a response structure that matches what our coordinator expects
        transformed = {
            "vinKey": vehicle.get("vin"),
            "vehicleConfig": {
                "vehicleDetail": {
                    "vehicle": {
                        "vin": vehicle.get("vin"),
                        "trim": {
                            "modelYear": vehicle_details.get("modelYear", ""),
                            "modelName": vehicle_details.get("modelCode", ""),
                        },
                        "mileage": str(vehicle_details.get("odometer", "0")),
                        "fuelType": 4 if vehicle.get("evStatus") == "E" else 1,
                    },
                },
                "vehicleFeature": {
                    "remoteFeature": {
                        "lock": "1" if bluelink_enabled else "0",
                        "unlock": "1" if bluelink_enabled else "0",
                        "start": "3" if fatc_available else "0",
                        "stop": "1" if fatc_available else "0",
                        "heatedSteeringWheel": "1" if steering_wheel_heat_capable else "0",
                        "heatedSideMirror": "1" if side_mirror_heat_capable else "0",
                        "heatedRearWindow": "1" if rear_window_heat_capable else "0",
                        "heatedSeat": "1" if has_heated_seats else "0",
                        "ventSeat": "1" if has_ventilated_seats else "0",
                        "steeringWheelStepLevel": "1",  # Hyundai typically has on/off only
                    },
                },
                "heatVentSeat": {
                    "driverSeat": seat_config_map.get("1", {"heatVentType": 0, "heatVentStep": 0}),
                    "passengerSeat": seat_config_map.get("2", {"heatVentType": 0, "heatVentStep": 0}),
                    "rearLeftSeat": seat_config_map.get("3", {"heatVentType": 0, "heatVentStep": 0}),
                    "rearRightSeat": seat_config_map.get("4", {"heatVentType": 0, "heatVentStep": 0}),
                },
            },
            "lastVehicleInfo": {
                "vehicleNickName": vehicle.get("nickName", "Hyundai Vehicle"),
                "vehicleStatusRpt": {
                    "vehicleStatus": {
                        "climate": {
                            "airCtrl": vehicle_status.get("airCtrlOn", False),
                            "defrost": vehicle_status.get("defrost", False),
                            "airTemp": {
                                "value": str(vehicle_status.get("airTemp", {}).get("value", "72")),
                                "unit": 1,
                            },
                            "heatingAccessory": {
                                "steeringWheel": 1 if vehicle_status.get("steerWheelHeat") else 0,
                                "sideMirror": 1 if vehicle_status.get("sideMirrorHeat") else 0,
                                "rearWindow": 1 if vehicle_status.get("sideBackWindowHeat") else 0,
                            },
                        },
                        "engine": vehicle_status.get("engine", False),
                        "doorLock": vehicle_status.get("doorLock", True),
                        "doorStatus": {
                            "frontLeft": 1 if vehicle_status.get("doorOpen", {}).get("frontLeft") else 0,
                            "frontRight": 1 if vehicle_status.get("doorOpen", {}).get("frontRight") else 0,
                            "backLeft": 1 if vehicle_status.get("doorOpen", {}).get("backLeft") else 0,
                            "backRight": 1 if vehicle_status.get("doorOpen", {}).get("backRight") else 0,
                            "trunk": 1 if vehicle_status.get("trunkOpen") else 0,
                            "hood": 1 if vehicle_status.get("hoodOpen") else 0,
                        },
                        "lowFuelLight": vehicle_status.get("lowFuelLight", False),
                        "ign3": vehicle_status.get("ign3", False),
                        "transCond": vehicle_status.get("transCond", True),
                        "dateTime": {
                            "utc": vehicle_status.get("dateTime", "").replace("-", "").replace("T", "").replace(":", "").replace("Z", ""),
                        },
                        "batteryStatus": {
                            "stateOfCharge": vehicle_status.get("battery", {}).get("batSoc", 0),
                        },
                    },
                },
            },
        }
        
        # Add EV-specific data if applicable
        if vehicle.get("evStatus") == "E":
            ev_status = vehicle_status.get("evStatus", {})
            transformed["lastVehicleInfo"]["vehicleStatusRpt"]["vehicleStatus"]["evStatus"] = {
                "batteryCharge": ev_status.get("batteryCharge", False),
                "batteryStatus": ev_status.get("batteryStatus", 0),
                "batteryPlugin": ev_status.get("batteryPlugin", 0),
                "drvDistance": ev_status.get("drvDistance", []),
                "remainChargeTime": ev_status.get("remainTime2", {}),
                "targetSOC": ev_status.get("reservChargeInfos", {}).get("targetSOClist", []),
            }
        
        # Add location if available
        if location:
            transformed["lastVehicleInfo"]["location"] = {
                "coord": location.get("coord", {}),
                "head": location.get("head", 0),
                "speed": location.get("speed", {}),
            }
        
        return transformed

    async def request_vehicle_data_sync(self, vehicle_id: str):
        """Request fresh vehicle data sync."""
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        headers = self._get_vehicle_headers(vehicle)
        headers["REFRESH"] = "true"
        
        url = HYUNDAI_API_URL_BASE + "rcs/rvs/vehicleStatus"
        await self._get_request_with_logging_and_errors_raised(
            url=url,
            headers=headers,
        )

    async def lock(self, vehicle_id: str):
        """Lock the vehicle."""
        _LOGGER.info("===== HYUNDAI LOCK CALLED =====")
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        headers = self._get_vehicle_headers(vehicle)
        
        url = HYUNDAI_API_URL_BASE + "rcs/rdo/off"
        _LOGGER.debug("Hyundai lock URL: %s", url)
        _LOGGER.debug("Hyundai lock headers: %s", {k: v for k, v in headers.items() if k.lower() not in ['accesstoken', 'bluelinkservicepin']})
        
        # BlueLink API expects empty body for lock/unlock
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body={},
            headers=headers,
        )
        _LOGGER.debug("Hyundai lock response: %s", await response.text())

    async def unlock(self, vehicle_id: str):
        """Unlock the vehicle."""
        _LOGGER.info("===== HYUNDAI UNLOCK CALLED =====")
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        headers = self._get_vehicle_headers(vehicle)
        
        url = HYUNDAI_API_URL_BASE + "rcs/rdo/on"
        _LOGGER.debug("Hyundai unlock URL: %s", url)
        _LOGGER.debug("Hyundai unlock headers: %s", {k: v for k, v in headers.items() if k.lower() not in ['accesstoken', 'bluelinkservicepin']})
        
        # BlueLink API expects empty body for lock/unlock
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body={},
            headers=headers,
        )
        _LOGGER.debug("Hyundai unlock response: %s", await response.text())

    async def start_climate(
            self,
            vehicle_id: str,
            set_temp: int,
            defrost: bool,
            climate: bool,
            heating: bool,
            steering_wheel_heat: int = 0,
            driver_seat: SeatSettings | None = None,
            passenger_seat: SeatSettings | None = None,
            left_rear_seat: SeatSettings | None = None,
            right_rear_seat: SeatSettings | None = None,
    ):
        """Start climate control."""
        _LOGGER.info("===== HYUNDAI START_CLIMATE CALLED =====")
        _LOGGER.info(
            "start_climate params: temp=%s, defrost=%s, climate=%s, heating=%s, steering_wheel=%s",
            set_temp, defrost, climate, heating, steering_wheel_heat
        )
        
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        headers = self._get_vehicle_headers(vehicle)
        
        is_ev = vehicle.get("evStatus") == "E"
        generation = vehicle.get("generation", 2)
        
        if is_ev:
            url = HYUNDAI_API_URL_BASE + "evc/fatc/start"
        else:
            url = HYUNDAI_API_URL_BASE + "rcs/rsc/start"
        
        # Build climate request data
        if is_ev:
            data = {
                "airCtrl": int(climate),
                "airTemp": {"value": str(set_temp), "unit": 1},
                "defrost": defrost,
                "heating1": int(heating),
            }
            # Generation 3+ vehicles support seat heater and duration
            if generation >= 3:
                data["igniOnDuration"] = 10
                data["seatHeaterVentInfo"] = {
                    "drvSeatHeatState": _seat_settings_hyundai(driver_seat),
                    "astSeatHeatState": _seat_settings_hyundai(passenger_seat),
                    "rlSeatHeatState": _seat_settings_hyundai(left_rear_seat),
                    "rrSeatHeatState": _seat_settings_hyundai(right_rear_seat),
                }
        else:
            # ICE vehicle
            data = {
                "Ims": 0,
                "airCtrl": int(climate),
                "airTemp": {"unit": 1, "value": set_temp},
                "defrost": defrost,
                "heating1": int(heating),
                "igniOnDuration": 10,
                "seatHeaterVentInfo": {
                    "drvSeatHeatState": _seat_settings_hyundai(driver_seat),
                    "astSeatHeatState": _seat_settings_hyundai(passenger_seat),
                    "rlSeatHeatState": _seat_settings_hyundai(left_rear_seat),
                    "rrSeatHeatState": _seat_settings_hyundai(right_rear_seat),
                },
                "username": self.username,
                "vin": vehicle.get("vin"),
            }
        
        _LOGGER.debug("Hyundai start_climate data: %s", data)
        
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body=data,
            headers=headers,
        )
        _LOGGER.debug("Hyundai start_climate response: %s", await response.text())

    async def stop_climate(self, vehicle_id: str):
        """Stop climate control."""
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        headers = self._get_vehicle_headers(vehicle)
        
        is_ev = vehicle.get("evStatus") == "E"
        
        if is_ev:
            url = HYUNDAI_API_URL_BASE + "evc/fatc/stop"
        else:
            url = HYUNDAI_API_URL_BASE + "rcs/rsc/stop"
        
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body={},
            headers=headers,
        )
        _LOGGER.debug("Hyundai stop_climate response: %s", await response.text())

    async def start_charge(self, vehicle_id: str):
        """Start charging (EV only)."""
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        if vehicle.get("evStatus") != "E":
            _LOGGER.warning("start_charge called on non-EV vehicle")
            return
        
        headers = self._get_vehicle_headers(vehicle)
        url = HYUNDAI_API_URL_BASE + "evc/charge/start"
        
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body={},
            headers=headers,
        )
        _LOGGER.debug("Hyundai start_charge response: %s", await response.text())

    async def stop_charge(self, vehicle_id: str):
        """Stop charging (EV only)."""
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        if vehicle.get("evStatus") != "E":
            _LOGGER.warning("stop_charge called on non-EV vehicle")
            return
        
        headers = self._get_vehicle_headers(vehicle)
        url = HYUNDAI_API_URL_BASE + "evc/charge/stop"
        
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body={},
            headers=headers,
        )
        _LOGGER.debug("Hyundai stop_charge response: %s", await response.text())

    async def set_charge_limits(
            self,
            vehicle_id: str,
            ac_limit: int,
            dc_limit: int,
    ):
        """Set charge limits (EV only)."""
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        if vehicle.get("evStatus") != "E":
            _LOGGER.warning("set_charge_limits called on non-EV vehicle")
            return
        
        headers = self._get_vehicle_headers(vehicle)
        url = HYUNDAI_API_URL_BASE + "evc/charge/targetsoc/set"
        
        data = {
            "targetSOClist": [
                {"plugType": 0, "targetSOClevel": int(dc_limit)},
                {"plugType": 1, "targetSOClevel": int(ac_limit)},
            ]
        }
        
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body=data,
            headers=headers,
        )
        _LOGGER.debug("Hyundai set_charge_limits response: %s", await response.text())

    async def check_last_action_finished(self, vehicle_id: str) -> bool:
        """Check if last action is finished (placeholder for compatibility)."""
        # Hyundai API doesn't have the same action tracking as Kia
        return True
