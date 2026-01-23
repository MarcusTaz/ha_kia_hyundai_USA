"""UsGenesis - Genesis Connected Services API for USA.

Based on the EU library's implementation.
Supports both:
1. Direct login with username/password + PIN (older accounts)
2. OTP authentication if required by the account (newer accounts)

The API is nearly identical to Hyundai, just with different endpoints and brand indicator.
"""

import logging
import asyncio

from datetime import datetime
import ssl
import uuid
from collections.abc import Callable
from typing import Any
from collections.abc import Coroutine
import certifi

import pytz
import time

from functools import partial
from aiohttp import ClientSession, ClientResponse

from .errors import AuthError, ActionAlreadyInProgressError
from .const import (
    GENESIS_API_URL_HOST,
    GENESIS_LOGIN_API_BASE,
    GENESIS_API_URL_BASE,
    SeatSettings,
)
from .util_http import request_with_logging_bluelink, request_with_active_session

_LOGGER = logging.getLogger(__name__)


def _seat_settings_genesis(level: SeatSettings | None) -> int:
    """Convert seat setting to Genesis API value (same as Hyundai)."""
    if level is None:
        return 0
    
    level_value = level.value if hasattr(level, 'value') else level
    
    if level_value == 6:  # HeatHigh
        return 3
    elif level_value == 5:  # HeatMedium
        return 2
    elif level_value == 4:  # HeatLow
        return 1
    elif level_value == 3:  # CoolHigh
        return 3
    elif level_value == 2:  # CoolMedium
        return 2
    elif level_value == 1:  # CoolLow
        return 1
    else:  # NONE (0) or unknown
        return 0


class UsGenesis:
    """Genesis Connected Services USA API client."""
    
    _ssl_context = None
    access_token: str | None = None
    refresh_token: str | None = None
    session_id: str | None = None  # For OTP-based auth
    vehicles: list[dict] | None = None
    last_action = None
    otp_key: str | None = None
    otp_xid: str | None = None
    notify_type: str | None = None

    def __init__(
            self,
            username: str,
            password: str,
            pin: str,
            otp_callback: Callable[..., Coroutine[Any, Any, Any]] | None = None,
            device_id: str | None = None,
            client_session: ClientSession | None = None
    ):
        """Initialize Genesis API client.
        
        Parameters
        ----------
        username : str
            User email address
        password : str
            User password
        pin : str
            Genesis Connected Services PIN (4 digits)
        otp_callback : Callable, optional
            OTP handler if account requires OTP. Called with:
            - stage='choose_destination' -> return {'notify_type': 'EMAIL'|'SMS'}
            - stage='input_code' -> return {'otp_code': '<code>'}
        device_id : str, optional
            Device identifier for API
        """
        self.username = username
        self.password = password
        self.pin = pin
        self.otp_callback = otp_callback
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
            new_ssl_context.options |= 0x4
            self._ssl_context = new_ssl_context
        return self._ssl_context

    def _api_headers(self) -> dict:
        """Generate API headers for Genesis Connected Services."""
        ts = time.time()
        utc_offset_hours = int(
            (datetime.fromtimestamp(ts) - datetime.utcfromtimestamp(ts)).total_seconds() / 60 / 60
        )
        
        origin = "https://" + GENESIS_API_URL_HOST
        referer = origin + "/login"
        
        headers = {
            "content-type": "application/json;charset=UTF-8",
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.142 Safari/537.36",
            "host": GENESIS_API_URL_HOST,
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
            "brandIndicator": "G",  # Genesis brand indicator
            "client_id": "m66129Bb-em93-SPAHYN-bZ91-am4540zp19920",  # Uses Hyundai client ID
            "clientSecret": "v558o935-6nne-423i-baa8",
        }
        return headers

    def _get_authenticated_headers(self) -> dict:
        """Get headers with authentication tokens."""
        headers = self._api_headers()
        headers["username"] = self.username
        headers["accessToken"] = self.access_token or ""
        headers["blueLinkServicePin"] = self.pin  # Genesis also uses "blueLinkServicePin"
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

    async def _send_otp(self, notify_type: str) -> dict:
        """Send OTP to email or phone."""
        if notify_type not in ("EMAIL", "SMS"):
            raise ValueError(f"Invalid notify_type {notify_type}")
        
        url = GENESIS_LOGIN_API_BASE + "sendOTP"
        self.notify_type = notify_type
        
        headers = self._api_headers()
        if self.otp_key:
            headers["otpKey"] = self.otp_key
        if self.otp_xid:
            headers["xid"] = self.otp_xid
        headers["notifyType"] = notify_type
        
        _LOGGER.debug("Sending Genesis OTP to %s", notify_type)
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body={},
            headers=headers,
        )
        return await response.json()

    async def _verify_otp(self, otp_code: str) -> dict:
        """Verify OTP code."""
        url = GENESIS_LOGIN_API_BASE + "verifyOTP"
        
        headers = self._api_headers()
        if self.otp_key:
            headers["otpKey"] = self.otp_key
        if self.otp_xid:
            headers["xid"] = self.otp_xid
        if self.notify_type:
            headers["notifyType"] = self.notify_type
        
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body={"otp": otp_code},
            headers=headers,
        )
        
        response_json = await response.json()
        _LOGGER.debug("Genesis OTP verification response: %s", response_json)
        
        # Get tokens from headers
        self.access_token = response.headers.get("accessToken")
        self.session_id = response.headers.get("sid")
        
        return response_json

    async def login(self):
        """Login to Genesis Connected Services.
        
        Tries direct OAuth login first. If OTP is required, handles the OTP flow.
        """
        _LOGGER.info("========== GENESIS LOGIN START ==========")
        _LOGGER.info("Genesis login attempt for user: %s", self.username)
        _LOGGER.info("Using API host: %s", GENESIS_API_URL_HOST)
        _LOGGER.info("Login URL: %s", GENESIS_LOGIN_API_BASE + "oauth/token")
        _LOGGER.info("OTP callback provided: %s", self.otp_callback is not None)
        
        # First, try the OAuth token endpoint (works for some accounts)
        url = GENESIS_LOGIN_API_BASE + "oauth/token"
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
        _LOGGER.info("Genesis login response status: %s", response.status)
        _LOGGER.info("Genesis login response keys: %s", list(response_json.keys()))
        
        # Log specific fields for debugging (not sensitive data)
        if "access_token" in response_json:
            _LOGGER.info("Response contains access_token: YES (length: %d)", len(response_json.get("access_token", "")))
        else:
            _LOGGER.info("Response contains access_token: NO")
        
        if "otpKey" in response_json:
            _LOGGER.info("Response contains otpKey: YES")
        else:
            _LOGGER.info("Response contains otpKey: NO")
            
        if "errorCode" in response_json:
            _LOGGER.info("Response errorCode: %s", response_json.get("errorCode"))
            _LOGGER.info("Response errorMessage: %s", response_json.get("errorMessage"))
            _LOGGER.info("Response errorSubCode: %s", response_json.get("errorSubCode"))
            _LOGGER.info("Response errorSubMessage: %s", response_json.get("errorSubMessage"))
        
        _LOGGER.info("Full response (for debugging): %s", response_json)
        
        # Check if we got an access token directly
        if response_json.get("access_token"):
            self.access_token = response_json["access_token"]
            self.refresh_token = response_json.get("refresh_token")
            _LOGGER.info("========== GENESIS LOGIN SUCCESS (direct auth) ==========")
            return
        
        # Check if OTP is required
        if "otpKey" in response_json or response_json.get("responseCode") == "OTP_REQUIRED":
            _LOGGER.info("========== GENESIS OTP REQUIRED ==========")
            _LOGGER.info("Genesis account requires OTP authentication")
            
            if self.otp_callback is None:
                _LOGGER.error("OTP required but no callback provided!")
                raise AuthError("OTP required but no OTP callback provided. Please reconfigure with OTP support.")
            
            self.otp_key = response_json.get("otpKey", "")
            self.otp_xid = response.headers.get("xid", "")
            _LOGGER.info("OTP key received: %s", bool(self.otp_key))
            _LOGGER.info("OTP xid received: %s", bool(self.otp_xid))
            
            # Get OTP destination from callback
            ctx_choice = {
                "stage": "choose_destination",
                "hasEmail": True,
                "hasPhone": True,
                "email": response_json.get("email", ""),
                "phone": response_json.get("phone", ""),
            }
            _LOGGER.info("Calling OTP callback for destination choice...")
            callback_response = await self.otp_callback(ctx_choice)
            notify_type = str(callback_response.get("notify_type", "EMAIL")).upper()
            _LOGGER.info("OTP destination chosen: %s", notify_type)
            
            # Send OTP
            _LOGGER.info("Sending OTP to %s...", notify_type)
            await self._send_otp(notify_type)
            _LOGGER.info("OTP send request completed")
            
            # Get OTP code from callback
            ctx_code = {
                "stage": "input_code",
                "notify_type": notify_type,
            }
            _LOGGER.info("Calling OTP callback for code input...")
            otp_response = await self.otp_callback(ctx_code)
            otp_code = str(otp_response.get("otp_code", "")).strip()
            _LOGGER.info("OTP code received (length: %d)", len(otp_code))
            
            if not otp_code:
                raise AuthError("OTP code required")
            
            # Verify OTP
            _LOGGER.info("Verifying OTP code...")
            await self._verify_otp(otp_code)
            _LOGGER.info("OTP verification completed, access_token: %s, session_id: %s", 
                        bool(self.access_token), bool(self.session_id))
            
            if not self.access_token and not self.session_id:
                raise AuthError("OTP verification failed - no token received")
            
            _LOGGER.info("========== GENESIS LOGIN SUCCESS (OTP auth) ==========")
            return
        
        # Login failed - log everything we know
        _LOGGER.error("========== GENESIS LOGIN FAILED ==========")
        _LOGGER.error("No access_token and no OTP flow triggered")
        _LOGGER.error("Response keys: %s", list(response_json.keys()))
        _LOGGER.error("Full response: %s", response_json)
        
        error_msg = response_json.get("errorMessage", response_json.get("message", "Unknown error"))
        raise AuthError(f"Genesis login failed: {error_msg}")

    async def get_vehicles(self):
        """Get list of vehicles for the account."""
        if self.access_token is None:
            await self.login()
        
        url = GENESIS_API_URL_BASE + "enrollment/details/" + self.username
        headers = self._get_authenticated_headers()
        
        response = await self._get_request_with_logging_and_errors_raised(
            url=url,
            headers=headers,
        )
        
        response_json = await response.json()
        _LOGGER.debug("Genesis get_vehicles response: %s", response_json)
        
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
        """Get cached vehicle status from Genesis API."""
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        headers = self._get_vehicle_headers(vehicle)
        
        url = GENESIS_API_URL_BASE + "rcs/rvs/vehicleStatus"
        response = await self._get_request_with_logging_and_errors_raised(
            url=url,
            headers=headers,
        )
        response_json = await response.json()
        _LOGGER.debug("Genesis vehicle status response: %s", response_json)
        
        # Get vehicle details
        details_url = GENESIS_API_URL_BASE + "enrollment/details/" + self.username
        details_response = await self._get_request_with_logging_and_errors_raised(
            url=details_url,
            headers=self._get_authenticated_headers(),
        )
        details_json = await details_response.json()
        
        vehicle_details = {}
        for entry in details_json.get("enrolledVehicleDetails", []):
            if entry.get("vehicleDetails", {}).get("regid") == vehicle_id:
                vehicle_details = entry.get("vehicleDetails", {})
                break
        
        # Get location
        location = None
        try:
            loc_url = GENESIS_API_URL_BASE + "rcs/rfc/findMyCar"
            loc_response = await self._get_request_with_logging_and_errors_raised(
                url=loc_url,
                headers=headers,
            )
            loc_json = await loc_response.json()
            if loc_json.get("coord"):
                location = loc_json
        except Exception as e:
            _LOGGER.debug("Failed to get location: %s", e)
        
        # Transform to match Kia format
        vehicle_status = response_json.get("vehicleStatus", {})
        
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
                        "heatedSteeringWheel": "1" if vehicle_status.get("steerWheelHeat") is not None else "0",
                        "heatedSeat": "1",
                        "ventSeat": "1" if vehicle.get("evStatus") == "E" else "0",
                        "steeringWheelStepLevel": "1",
                    },
                },
                "heatVentSeat": {
                    "driverSeat": {"heatVentType": 3, "heatVentStep": 3},
                    "passengerSeat": {"heatVentType": 3, "heatVentStep": 3},
                    "rearLeftSeat": {"heatVentType": 1, "heatVentStep": 2},
                    "rearRightSeat": {"heatVentType": 1, "heatVentStep": 2},
                },
            },
            "lastVehicleInfo": {
                "vehicleNickName": vehicle.get("nickName", "Genesis Vehicle"),
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
        
        url = GENESIS_API_URL_BASE + "rcs/rvs/vehicleStatus"
        await self._get_request_with_logging_and_errors_raised(
            url=url,
            headers=headers,
        )

    async def lock(self, vehicle_id: str):
        """Lock the vehicle."""
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        headers = self._get_vehicle_headers(vehicle)
        headers["APPCLOUD-VIN"] = vehicle.get("vin", "")
        
        url = GENESIS_API_URL_BASE + "rcs/rdo/off"
        data = {"userName": self.username, "vin": vehicle.get("vin")}
        
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body=data,
            headers=headers,
        )
        _LOGGER.debug("Genesis lock response: %s", await response.text())

    async def unlock(self, vehicle_id: str):
        """Unlock the vehicle."""
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        headers = self._get_vehicle_headers(vehicle)
        headers["APPCLOUD-VIN"] = vehicle.get("vin", "")
        
        url = GENESIS_API_URL_BASE + "rcs/rdo/on"
        data = {"userName": self.username, "vin": vehicle.get("vin")}
        
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body=data,
            headers=headers,
        )
        _LOGGER.debug("Genesis unlock response: %s", await response.text())

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
        _LOGGER.info("===== GENESIS START_CLIMATE CALLED =====")
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
            url = GENESIS_API_URL_BASE + "evc/fatc/start"
        else:
            url = GENESIS_API_URL_BASE + "rcs/rsc/start"
        
        if is_ev:
            data = {
                "airCtrl": int(climate),
                "airTemp": {"value": str(set_temp), "unit": 1},
                "defrost": defrost,
                "heating1": int(heating),
            }
            if generation >= 3:
                data["igniOnDuration"] = 10
                data["seatHeaterVentInfo"] = {
                    "drvSeatHeatState": _seat_settings_genesis(driver_seat),
                    "astSeatHeatState": _seat_settings_genesis(passenger_seat),
                    "rlSeatHeatState": _seat_settings_genesis(left_rear_seat),
                    "rrSeatHeatState": _seat_settings_genesis(right_rear_seat),
                }
        else:
            data = {
                "Ims": 0,
                "airCtrl": int(climate),
                "airTemp": {"unit": 1, "value": set_temp},
                "defrost": defrost,
                "heating1": int(heating),
                "igniOnDuration": 10,
                "seatHeaterVentInfo": {
                    "drvSeatHeatState": _seat_settings_genesis(driver_seat),
                    "astSeatHeatState": _seat_settings_genesis(passenger_seat),
                    "rlSeatHeatState": _seat_settings_genesis(left_rear_seat),
                    "rrSeatHeatState": _seat_settings_genesis(right_rear_seat),
                },
                "username": self.username,
                "vin": vehicle.get("vin"),
            }
        
        _LOGGER.debug("Genesis start_climate data: %s", data)
        
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body=data,
            headers=headers,
        )
        _LOGGER.debug("Genesis start_climate response: %s", await response.text())

    async def stop_climate(self, vehicle_id: str):
        """Stop climate control."""
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        headers = self._get_vehicle_headers(vehicle)
        
        is_ev = vehicle.get("evStatus") == "E"
        
        if is_ev:
            url = GENESIS_API_URL_BASE + "evc/fatc/stop"
        else:
            url = GENESIS_API_URL_BASE + "rcs/rsc/stop"
        
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body={},
            headers=headers,
        )
        _LOGGER.debug("Genesis stop_climate response: %s", await response.text())

    async def start_charge(self, vehicle_id: str):
        """Start charging (EV only)."""
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        if vehicle.get("evStatus") != "E":
            _LOGGER.warning("start_charge called on non-EV vehicle")
            return
        
        headers = self._get_vehicle_headers(vehicle)
        url = GENESIS_API_URL_BASE + "evc/charge/start"
        
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body={},
            headers=headers,
        )
        _LOGGER.debug("Genesis start_charge response: %s", await response.text())

    async def stop_charge(self, vehicle_id: str):
        """Stop charging (EV only)."""
        if self.access_token is None:
            await self.login()
        
        vehicle = await self.find_vehicle(vehicle_id)
        if vehicle.get("evStatus") != "E":
            _LOGGER.warning("stop_charge called on non-EV vehicle")
            return
        
        headers = self._get_vehicle_headers(vehicle)
        url = GENESIS_API_URL_BASE + "evc/charge/stop"
        
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body={},
            headers=headers,
        )
        _LOGGER.debug("Genesis stop_charge response: %s", await response.text())

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
        url = GENESIS_API_URL_BASE + "evc/charge/targetsoc/set"
        
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
        _LOGGER.debug("Genesis set_charge_limits response: %s", await response.text())

    async def check_last_action_finished(self, vehicle_id: str) -> bool:
        """Check if last action is finished (placeholder for compatibility)."""
        return True
