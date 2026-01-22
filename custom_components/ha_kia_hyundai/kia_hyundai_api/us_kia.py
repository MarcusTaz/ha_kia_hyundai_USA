"""UsKia - Fixed version with working OTP for USA.

Key fixes from the original kia-hyundai-api:
1. Updated headers to match current Kia iOS app (appversion, secretkey, clientid, etc.)
2. Fixed OTP flow to include _complete_login_with_otp step after OTP verification
3. Added tncFlag to login payload
4. Added clientuuid header generation
"""

import logging
import asyncio

from datetime import datetime
import random
import string
import secrets
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
from .const import API_URL_BASE, API_URL_HOST, SeatSettings
from .util_http import request_with_logging, request_with_active_session

_LOGGER = logging.getLogger(__name__)


def _seat_settings(level: SeatSettings | None) -> dict:
    """Derive the seat settings from a seat setting enum."""
    match level:
        case SeatSettings.HeatHigh:
            return {
                "heatVentType": 1,
                "heatVentLevel": 4,
                "heatVentStep": 1,
            }
        case SeatSettings.HeatMedium:
            return {
                "heatVentType": 1,
                "heatVentLevel": 3,
                "heatVentStep": 2,
            }
        case SeatSettings.HeatLow:
            return {
                "heatVentType": 1,
                "heatVentLevel": 2,
                "heatVentStep": 3,
            }
        case SeatSettings.CoolHigh:
            return {
                "heatVentType": 2,
                "heatVentLevel": 4,
                "heatVentStep": 1,
            }
        case SeatSettings.CoolMedium:
            return {
                "heatVentType": 2,
                "heatVentLevel": 3,
                "heatVentStep": 2,
            }
        case SeatSettings.CoolLow:
            return {
                "heatVentType": 2,
                "heatVentLevel": 2,
                "heatVentStep": 3,
            }
        case _:
            return {
                "heatVentType": 0,
                "heatVentLevel": 1,
                "heatVentStep": 0,
            }


class UsKia:
    """Kia USA API client with fixed OTP support."""
    
    _ssl_context = None
    session_id: str | None = None
    otp_key: str | None = None
    otp_xid: str | None = None  # Store xid separately for OTP flow
    notify_type: str | None = None
    vehicles: list[dict] | None = None
    last_action = None

    def __init__(
            self,
            username: str,
            password: str,
            otp_callback: Callable[..., Coroutine[Any, Any, Any]],
            device_id: str | None = None,
            refresh_token: str | None = None,
            client_session: ClientSession | None = None
                ):
        """Login into cloud endpoints
        Parameters
        ----------
        username : str
            User email address
        password : str
            User password
        device_id : reused , optional
        refresh_token : stored rmtoken for session reuse
        otp_callback : Callable[..., Coroutine[Any, Any, Any]]
            Non-interactive OTP handler. Called twice:
            - stage='choose_destination' -> return {'notify_type': 'EMAIL'|'SMS'}
            - stage='input_code' -> return {'otp_code': '<code>'}
        """
        self.username = username
        self.password = password
        self.otp_callback = otp_callback
        # Use UUID format for device_id like the iOS app
        self.device_id = device_id or str(uuid.uuid4()).upper()
        self.refresh_token = refresh_token
        if client_session is None:
            self.api_session = ClientSession(raise_for_status=True)
        else:
            self.api_session = client_session

    async def get_ssl_context(self):
        if self._ssl_context is None:
            loop = asyncio.get_running_loop()
            new_ssl_context = await loop.run_in_executor(None, partial(ssl.create_default_context, cafile=certifi.where()))
            await loop.run_in_executor(None, partial(new_ssl_context.load_default_certs))
            new_ssl_context.check_hostname = True
            new_ssl_context.verify_mode = ssl.CERT_REQUIRED
            new_ssl_context.set_ciphers("DEFAULT@SECLEVEL=1")
            new_ssl_context.options = (
                    ssl.OP_CIPHER_SERVER_PREFERENCE
            )
            new_ssl_context.options |= 0x4  # OP flag SSL_OP_ALLOW_UNSAFE_LEGACY_RENEGOTIATION
            self._ssl_context = new_ssl_context
        return self._ssl_context

    def _api_headers(self, vehicle_key: str | None = None) -> dict:
        """Generate API headers matching the EU library's iOS headers.
        
        These headers are copied exactly from hyundai-kia-connect-api KiaUvoApiUSA.py
        which has working OTP for the USA region.
        """
        offset = int(time.localtime().tm_gmtoff / 60 / 60)
        # Generate clientuuid as hash of device_id (same as EU library)
        client_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, self.device_id))
        
        headers = {
            "content-type": "application/json;charset=utf-8",
            "accept": "application/json",
            "accept-encoding": "gzip, deflate, br",
            "accept-language": "en-US,en;q=0.9",
            "accept-charset": "utf-8",
            "apptype": "L",
            "appversion": "7.22.0",
            "clientid": "SPACL716-APL",
            "clientuuid": client_uuid,
            "from": "SPA",
            "host": API_URL_HOST,
            "language": "0",
            "offset": str(offset),
            "ostype": "iOS",
            "osversion": "15.8.5",
            "phonebrand": "iPhone",
            "secretkey": "sydnat-9kykci-Kuhtep-h5nK",
            "to": "APIGW",
            "tokentype": "A",
            "user-agent": "KIAPrimo_iOS/37 CFNetwork/1335.0.3.4 Darwin/21.6.0",
            "deviceid": self.device_id,
            "date": datetime.now(tz=pytz.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"),
        }
        if self.session_id is not None:
            headers["sid"] = self.session_id
        if self.refresh_token is not None:
            headers["rmtoken"] = self.refresh_token
        if vehicle_key is not None:
            headers["vinkey"] = vehicle_key
        return headers
    
    def _otp_headers(self) -> dict:
        """Generate headers specifically for OTP requests."""
        headers = self._api_headers()
        if self.otp_key is not None:
            headers["otpkey"] = self.otp_key
        if self.notify_type is not None:
            headers["notifytype"] = self.notify_type
        if self.otp_xid is not None:
            headers["xid"] = self.otp_xid
        return headers

    @request_with_logging
    async def _post_request_with_logging_and_errors_raised(
            self,
            vehicle_key: str | None,
            url: str,
            json_body: dict,
            authed: bool = True,
            use_otp_headers: bool = False,
    ) -> ClientResponse:
        if authed and self.session_id is None:
            await self.login()
        if use_otp_headers:
            headers = self._otp_headers()
        else:
            headers = self._api_headers(vehicle_key=vehicle_key)
        return await self.api_session.post(
            url=url,
            json=json_body,
            headers=headers,
            ssl=await self.get_ssl_context()
        )

    @request_with_logging
    async def _get_request_with_logging_and_errors_raised(
            self,
            vehicle_key: str | None,
            url: str,
            authed: bool = True,
    ) -> ClientResponse:
        if authed and self.session_id is None:
            await self.login()
        headers = self._api_headers(vehicle_key=vehicle_key)
        return await self.api_session.get(
            url=url,
            headers=headers,
            ssl=await self.get_ssl_context()
        )

    async def _send_otp(self, notify_type: str) -> dict:
        """
        Send OTP to email or phone

        Parameters
        notify_type = "EMAIL" or "SMS"
        """
        if notify_type not in ("EMAIL", "SMS"):
            raise ValueError(f"Invalid notify_type {notify_type}")
        if self.otp_key is None:
            raise ValueError("OTP key required")
        if self.otp_xid is None:
            raise ValueError("OTP xid required")
        
        url = API_URL_BASE + "cmm/sendOTP"
        self.notify_type = notify_type
        
        _LOGGER.debug(f"Sending OTP to {notify_type}")
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                vehicle_key=None,
                url=url,
                json_body={},
                authed=False,
                use_otp_headers=True,
            )
        )
        _LOGGER.debug(f"Send OTP Response {await response.text()}")
        return await response.json()

    async def _verify_otp(self, otp_code: str) -> tuple[str, str]:
        """Verify OTP code and return sid and rmtoken"""
        if self.otp_key is None:
            raise ValueError("OTP key required")
        if self.otp_xid is None:
            raise ValueError("OTP xid required")
            
        url = API_URL_BASE + "cmm/verifyOTP"
        data = {"otp": otp_code}
        
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                vehicle_key=None,
                url=url,
                json_body=data,
                authed=False,
                use_otp_headers=True,
            )
        )
        
        response_text = await response.text()
        _LOGGER.debug(f"Verify OTP Response {response_text}")
        response_json = await response.json()
        
        if response_json["status"]["statusCode"] != 0:
            raise AuthError(
                f"OTP verification failed: {response_json['status']['errorMessage']}"
            )
        
        session_id = response.headers.get("sid")
        refresh_token = response.headers.get("rmtoken")
        
        if not session_id or not refresh_token:
            raise AuthError(
                f"No session_id or rmtoken in OTP verification response. Headers: {response.headers}"
            )
        
        return session_id, refresh_token

    async def _complete_login_with_otp(self, sid: str, rmtoken: str) -> str:
        """
        FIXED: Complete login with sid and rmtoken to get final session id.
        This step was missing in the original library!
        """
        url = API_URL_BASE + "prof/authUser"
        data = {
            "deviceKey": self.device_id,
            "deviceType": 2,
            "userCredential": {"userId": self.username, "password": self.password},
        }
        
        # Create headers with sid and rmtoken from OTP verification
        headers = self._api_headers()
        headers["sid"] = sid
        headers["rmtoken"] = rmtoken
        
        response = await self.api_session.post(
            url=url,
            json=data,
            headers=headers,
            ssl=await self.get_ssl_context()
        )
        
        response_text = await response.text()
        _LOGGER.debug(f"Complete Login Response {response_text}")
        
        final_sid = response.headers.get("sid")
        if not final_sid:
            raise AuthError(
                f"No final sid returned in complete login. Response: {response_text}"
            )
        
        return final_sid

    async def login(self):
        """ Login into cloud endpoints """
        url = API_URL_BASE + "prof/authUser"
        
        # FIXED: Added tncFlag to login payload
        data = {
            "deviceKey": self.device_id,
            "deviceType": 2,
            "userCredential": {"userId": self.username, "password": self.password},
            "tncFlag": 1,  # Added - terms and conditions flag
        }
        
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                vehicle_key=None,
                url=url,
                json_body=data,
                authed=False,
            )
        )
        
        response_text = await response.text()
        _LOGGER.debug(f"Complete Login Response {response_text}")
        
        self.session_id = response.headers.get("sid")
        _LOGGER.debug(f"Session ID {self.session_id}")
        
        if self.session_id:
            _LOGGER.debug(f"got session id {self.session_id}")
            return
        
        response_json = await response.json()
        
        if "payload" in response_json and "otpKey" in response_json["payload"]:
            payload = response_json["payload"]
            if payload.get("rmTokenExpired"):
                _LOGGER.info("Stored rmtoken has expired, need new OTP")
                self.refresh_token = None
            
            try:
                self.otp_key = payload["otpKey"]
                self.otp_xid = response.headers.get("xid", "")  # Store xid for OTP flow
                
                _LOGGER.info("OTP required for login")
                ctx_choice = {
                    "stage": "choose_destination",
                    "hasEmail": bool(payload.get("hasEmail")),
                    "hasPhone": bool(payload.get("hasPhone")),
                    "email": payload.get("email", 'N/A'),
                    "phone": payload.get("phone", 'N/A'),
                }
                _LOGGER.debug(f"OTP callback stage choice args: {ctx_choice}")
                callback_response = await self.otp_callback(ctx_choice)
                _LOGGER.debug(f"OTP callback response {callback_response}")
                
                notify_type = str(callback_response.get("notify_type", "EMAIL")).upper()
                await self._send_otp(notify_type)
                
                ctx_code = {
                    "stage": "input_code",
                    "notify_type": notify_type,
                    "otpKey": self.otp_key,
                    "xid": self.otp_xid,
                }
                _LOGGER.debug(f"OTP callback stage input args: {ctx_code}")
                otp_callback_response = await self.otp_callback(ctx_code)
                otp_code = str(otp_callback_response.get("otp_code", "")).strip()
                
                if not otp_code:
                    raise AuthError("OTP code required")
                
                # FIXED: Use the proper OTP verification flow
                sid, rmtoken = await self._verify_otp(otp_code)
                
                # FIXED: Complete login with sid and rmtoken to get final session
                final_sid = await self._complete_login_with_otp(sid, rmtoken)
                
                self.session_id = final_sid
                self.refresh_token = rmtoken
                _LOGGER.info("OTP verification successful, login complete")
                return
                
            finally:
                self.otp_key = None
                self.otp_xid = None
                self.notify_type = None
        
        raise AuthError(
            f"No session id returned in login. Response: {response_text} headers {response.headers}"
        )

    @request_with_active_session
    async def get_vehicles(self):
        """
        Get list of vehicles for the account
        """
        url = API_URL_BASE + "ownr/gvl"
        response: ClientResponse = (
            await self._get_request_with_logging_and_errors_raised(
                vehicle_key=None,
                url=url
            )
        )
        response_json = await response.json()
        self.vehicles = response_json["payload"]["vehicleSummary"]

    async def find_vehicle_key(self, vehicle_id: str):
        if self.vehicles is None:
            await self.get_vehicles()
        if self.vehicles is None:
            raise ValueError("no vehicles found")
        for vehicle in self.vehicles:
            if vehicle["vehicleIdentifier"] == vehicle_id:
                return vehicle["vehicleKey"]
        raise ValueError(f"vehicle key for id:{vehicle_id} not found")

    @request_with_active_session
    async def get_cached_vehicle_status(self, vehicle_id: str):
        """Get cached vehicle status"""
        url = API_URL_BASE + "cmm/gvi"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        _LOGGER.debug("Getting cached status for vehicle_id=%s, vehicle_key=%s", vehicle_id, vehicle_key)
        # Payload format: Use US API values for climate support
        # seatHeatCoolOption and vehicleFeature must be "1" to get climate data
        body = {
            "vehicleConfigReq": {
                "airTempRange": "0",
                "maintenance": "1",
                "seatHeatCoolOption": "1",  # Must be 1 for seat climate data
                "vehicle": "1",
                "vehicleFeature": "1",  # Must be 1 for climate features
            },
            "vehicleInfoReq": {
                "drivingActivty": "0",
                "dtc": "1",
                "enrollment": "1",
                "functionalCards": "0",
                "location": "1",
                "vehicleStatus": "1",
                "weather": "0",
            },
            "vinKey": [vehicle_key],
        }
        response = await self._post_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
            json_body=body,
        )
        response_json = await response.json()
        return response_json["payload"]["vehicleInfoList"][0]

    @request_with_active_session
    async def request_vehicle_data_sync(self, vehicle_id: str):
        """Request vehicle to sync fresh data"""
        url = API_URL_BASE + "rems/rvs"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        body = {
            "requestType": 0  # value of 1 would return cached results instead of forcing update
        }
        await self._post_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
            json_body=body,
        )

    @request_with_active_session
    async def check_last_action_finished(
            self,
            vehicle_id: str,
    ) -> bool:
        url = API_URL_BASE + "cmm/gts"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        if self.last_action is None:
            _LOGGER.debug("no last action to check")
            return True
        body = {"xid": self.last_action["xid"]}
        response = await self._post_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
            json_body=body,
        )
        response_json = await response.json()
        finished = all(v == 0 for v in response_json["payload"].values())
        if finished:
            _LOGGER.debug("last action is finished")
            self.last_action = None
        return finished

    @request_with_active_session
    async def lock(self, vehicle_id: str):
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("{} still pending".format(self.last_action["name"]))
        url = API_URL_BASE + "rems/door/lock"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        response = await self._get_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
        )
        self.last_action = {
            "name": "lock",
            "xid": response.headers["Xid"]
        }

    @request_with_active_session
    async def unlock(self, vehicle_id: str):
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("{} still pending".format(self.last_action["name"]))
        url = API_URL_BASE + "rems/door/unlock"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        response = await self._get_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
        )
        self.last_action = {
            "name": "unlock",
            "xid": response.headers["Xid"]
        }

    @request_with_active_session
    async def start_climate(
            self,
            vehicle_id: str,
            set_temp: int,
            defrost: bool,
            climate: bool,
            heating: bool,
            driver_seat: SeatSettings | None = None,
            passenger_seat: SeatSettings | None = None,
            left_rear_seat: SeatSettings | None = None,
            right_rear_seat: SeatSettings | None = None,
    ):
        _LOGGER.info("===== US_KIA START_CLIMATE CALLED =====")
        _LOGGER.info(
            "start_climate params: temp=%s, defrost=%s, climate=%s, heating=%s, "
            "driver_seat=%s, passenger_seat=%s, left_rear=%s, right_rear=%s",
            set_temp, defrost, climate, heating,
            driver_seat, passenger_seat, left_rear_seat, right_rear_seat
        )
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("{} still pending".format(self.last_action["name"]))
        url = API_URL_BASE + "rems/start"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        body = {
            "remoteClimate": {
                "airCtrl": climate,
                "airTemp": {
                    "unit": 1,
                    "value": str(set_temp),
                },
                "defrost": defrost,
                "heatingAccessory": {
                    "rearWindow": int(heating),
                    "sideMirror": int(heating),
                    "steeringWheel": int(heating),
                },
                "ignitionOnDuration": {
                    "unit": 4,
                    "value": 9,
                },
            }
        }
        # Always include seat settings if any are provided OR if they have non-None/non-NONE values
        has_seat_settings = any([
            driver_seat is not None and driver_seat != SeatSettings.NONE,
            passenger_seat is not None and passenger_seat != SeatSettings.NONE,
            left_rear_seat is not None and left_rear_seat != SeatSettings.NONE,
            right_rear_seat is not None and right_rear_seat != SeatSettings.NONE,
        ])
        _LOGGER.debug("has_seat_settings=%s", has_seat_settings)
        
        if has_seat_settings:
            body["remoteClimate"]["heatVentSeat"] = {
                "driverSeat": _seat_settings(driver_seat),
                "passengerSeat": _seat_settings(passenger_seat),
                "rearLeftSeat": _seat_settings(left_rear_seat),
                "rearRightSeat": _seat_settings(right_rear_seat),
            }
            _LOGGER.debug("Seat settings payload: %s", body["remoteClimate"]["heatVentSeat"])
        response = await self._post_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
            json_body=body,
        )
        self.last_action = {
            "name": "start_climate",
            "xid": response.headers["Xid"]
        }

    @request_with_active_session
    async def stop_climate(self, vehicle_id: str):
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("{} still pending".format(self.last_action["name"]))
        url = API_URL_BASE + "rems/stop"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        response = await self._get_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
        )
        self.last_action = {
            "name": "stop_climate",
            "xid": response.headers["Xid"]
        }

    @request_with_active_session
    async def start_charge(self, vehicle_id: str):
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("{} still pending".format(self.last_action["name"]))
        url = API_URL_BASE + "evc/charge"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        body = {"chargeRatio": 100}
        response = await self._post_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
            json_body=body,
        )
        self.last_action = {
            "name": "start_charge",
            "xid": response.headers["Xid"]
        }

    @request_with_active_session
    async def stop_charge(self, vehicle_id: str):
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("{} still pending".format(self.last_action["name"]))
        url = API_URL_BASE + "evc/cancel"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        response = await self._get_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
        )
        self.last_action = {
            "name": "stop_charge",
            "xid": response.headers["Xid"]
        }

    @request_with_active_session
    async def set_charge_limits(
            self,
            vehicle_id: str,
            ac_limit: int,
            dc_limit: int,
    ):
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("{} still pending".format(self.last_action["name"]))
        url = API_URL_BASE + "evc/sts"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        body = {
            "targetSOClist": [
                {
                    "plugType": 0,
                    "targetSOClevel": dc_limit,
                },
                {
                    "plugType": 1,
                    "targetSOClevel": ac_limit,
                },
            ]
        }
        response = await self._post_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
            json_body=body,
        )
        self.last_action = {
            "name": "set_charge_limits",
            "xid": response.headers["Xid"]
        }
