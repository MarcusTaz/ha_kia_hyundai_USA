"""Genesis background polling must not call findMyCar or repeat PIN failures.

The vehicle coordinator refresh calls ``UsGenesis.get_cached_vehicle_status``.
These tests mock that HTTP layer so the update path can be checked without a
Genesis account.
"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiohttp import ClientError

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = REPO_ROOT / "custom_components" / "ha_kia_hyundai"
API_ROOT = COMPONENT_ROOT / "kia_hyundai_api"


def _ensure_package(name: str, path: Path) -> None:
    module = sys.modules.get(name)
    if module is not None and getattr(module, "__path__", None):
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    module.__package__ = name
    sys.modules[name] = module


def _load_module(name: str, path: Path):
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "__file__", None) == str(path):
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_genesis_api():
    """Load the Genesis client without importing Home Assistant."""
    _ensure_package("ha_kia_hyundai", COMPONENT_ROOT)
    _ensure_package("ha_kia_hyundai.kia_hyundai_api", API_ROOT)
    _load_module("ha_kia_hyundai.kia_hyundai_api.const", API_ROOT / "const.py")
    errors = _load_module("ha_kia_hyundai.kia_hyundai_api.errors", API_ROOT / "errors.py")
    _load_module("ha_kia_hyundai.kia_hyundai_api.util", API_ROOT / "util.py")
    _load_module("ha_kia_hyundai.kia_hyundai_api.util_http", API_ROOT / "util_http.py")
    genesis = _load_module(
        "ha_kia_hyundai.kia_hyundai_api.us_genesis",
        API_ROOT / "us_genesis.py",
    )
    return genesis, errors


_genesis, _errors = _load_genesis_api()
UsGenesis = _genesis.UsGenesis
PINLockedError = _errors.PINLockedError


class _JsonResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status = 200
        self.headers = {"Content-Type": "application/json"}

    async def json(self):
        return self._payload


def _vehicle_status(
    location: dict | None = None,
    date_time: str = "2026-11-20T12:00:00Z",
) -> dict:
    status = {
        "airCtrlOn": False,
        "defrost": False,
        "airTemp": {"value": "72"},
        "engine": False,
        "doorLock": True,
        "doorOpen": {},
        "lowFuelLight": False,
        "dateTime": date_time,
        "battery": {"batSoc": 80},
    }
    if location is not None:
        status["vehicleLocation"] = location
    return {"vehicleStatus": status}


def _enrollment(odometer: str = "10") -> dict:
    return {
        "enrolledVehicleDetails": [
            {
                "vehicleDetails": {
                    "regid": "reg1",
                    "modelYear": "2026",
                    "modelCode": "GV70",
                    "odometer": odometer,
                    "seatConfigurations": {"seatConfigs": []},
                    "steeringWheelHeatCapable": "NO",
                    "sideMirrorHeatCapable": "NO",
                    "rearWindowHeatCapable": "NO",
                    "fatcAvailable": "N",
                    "bluelinkEnabled": True,
                }
            }
        ]
    }


def _ready_api() -> UsGenesis:
    api = UsGenesis(
        username="user@example.com",
        password="secret",
        pin="1234",
        client_session=object(),
    )
    api.access_token = "token"
    api.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    api.vehicles = [
        {
            "id": "reg1",
            "regid": "reg1",
            "vin": "KMTTESTVIN0000001",
            "nickName": "GV70",
            "generation": 2,
            "evStatus": "N",
        }
    ]
    return api


def _mileage(data: dict) -> str:
    return data["vehicleConfig"]["vehicleDetail"]["vehicle"]["mileage"]


class GenesisPollingTests(unittest.IsolatedAsyncioTestCase):
    def _install_get(self, api: UsGenesis, handler):
        calls: list[str] = []

        async def fake_get(url, headers=None):
            calls.append(url)
            result = handler(url)
            if isinstance(result, Exception):
                raise result
            return result

        api._get_request_with_logging_and_errors_raised = fake_get
        return calls

    def _assert_no_find_my_car(self, urls: list[str]) -> None:
        for url in urls:
            self.assertNotIn("findMyCar", url)
            self.assertNotIn("/rfc/", url)

    async def test_update_does_not_call_find_my_car_and_keeps_status_location(self):
        api = _ready_api()
        location = {
            "coord": {"lat": 33.1, "lon": -84.2},
            "head": 90,
            "speed": {"value": 0, "unit": 0},
        }

        def handler(url):
            if url.endswith("rcs/rvs/vehicleStatus"):
                return _JsonResponse(_vehicle_status(location))
            if "enrollment/details/" in url:
                return _JsonResponse(_enrollment())
            if "findMyCar" in url:
                raise AssertionError(f"findMyCar was requested: {url}")
            raise AssertionError(f"unexpected URL {url}")

        calls = self._install_get(api, handler)

        first = await api.get_cached_vehicle_status("reg1")
        second = await api.get_cached_vehicle_status("reg1")

        self._assert_no_find_my_car(calls)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(first["lastVehicleInfo"]["location"]["coord"]["lat"], 33.1)
        self.assertEqual(second["lastVehicleInfo"]["location"]["coord"]["lon"], -84.2)
        # Enrollment is cached, so the second poll is status only.
        self.assertEqual(calls[-1].rsplit("/", 1)[-1], "vehicleStatus")

    async def test_update_omits_location_when_status_has_no_coordinates(self):
        api = _ready_api()

        def handler(url):
            if url.endswith("rcs/rvs/vehicleStatus"):
                return _JsonResponse(_vehicle_status())
            if "enrollment/details/" in url:
                return _JsonResponse(_enrollment())
            raise AssertionError(f"unexpected URL {url}")

        calls = self._install_get(api, handler)
        data = await api.get_cached_vehicle_status("reg1")

        self._assert_no_find_my_car(calls)
        self.assertNotIn("location", data["lastVehicleInfo"])

    async def test_pin_locked_status_call_is_not_retried_on_the_next_poll(self):
        api = _ready_api()

        def handler(url):
            if url.endswith("rcs/rvs/vehicleStatus"):
                return PINLockedError(
                    "BlueLink PIN locked: Your PIN has been locked for 5 minutes."
                )
            raise AssertionError(f"unexpected URL {url}")

        calls = self._install_get(api, handler)

        with self.assertRaises(PINLockedError):
            await api.get_cached_vehicle_status("reg1")
        with self.assertRaises(PINLockedError):
            await api.get_cached_vehicle_status("reg1")

        self.assertEqual(len(calls), 1)
        self._assert_no_find_my_car(calls)

    async def test_incorrect_pin_client_error_is_not_retried_on_the_next_poll(self):
        api = _ready_api()

        def handler(url):
            if url.endswith("rcs/rvs/vehicleStatus"):
                return ClientError("BlueLink API error: IDM_PIN_607 incorrect PIN")
            raise AssertionError(f"unexpected URL {url}")

        calls = self._install_get(api, handler)

        with self.assertRaises(ClientError):
            await api.get_cached_vehicle_status("reg1")
        with self.assertRaises(PINLockedError):
            await api.get_cached_vehicle_status("reg1")

        self.assertEqual(len(calls), 1)
        self._assert_no_find_my_car(calls)

    async def test_pin_error_on_enrollment_does_not_repeat_that_call(self):
        api = _ready_api()

        def handler(url):
            if url.endswith("rcs/rvs/vehicleStatus"):
                return _JsonResponse(_vehicle_status())
            if "enrollment/details/" in url:
                return PINLockedError(
                    "BlueLink PIN locked: Your pin has been locked permanently, "
                    "please contact the call center."
                )
            raise AssertionError(f"unexpected URL {url}")

        calls = self._install_get(api, handler)

        with self.assertRaises(PINLockedError):
            await api.get_cached_vehicle_status("reg1")
        with self.assertRaises(PINLockedError):
            await api.get_cached_vehicle_status("reg1")

        enrollment_calls = [url for url in calls if "enrollment/details/" in url]
        status_calls = [url for url in calls if url.endswith("rcs/rvs/vehicleStatus")]
        self.assertEqual(enrollment_calls, [enrollment_calls[0]])
        self.assertEqual(len(enrollment_calls), 1)
        self.assertEqual(len(status_calls), 2)
        self._assert_no_find_my_car(calls)

    async def test_non_pin_errors_are_still_retried_on_the_next_poll(self):
        api = _ready_api()

        def handler(url):
            if url.endswith("rcs/rvs/vehicleStatus"):
                return ClientError("BlueLink API error: scheduled maintenance")
            raise AssertionError(f"unexpected URL {url}")

        calls = self._install_get(api, handler)

        with self.assertRaises(ClientError):
            await api.get_cached_vehicle_status("reg1")
        with self.assertRaises(ClientError):
            await api.get_cached_vehicle_status("reg1")

        self.assertEqual(len(calls), 2)
        self._assert_no_find_my_car(calls)


    async def test_enrollment_refreshes_when_the_car_reports_new_status(self):
        api = _ready_api()
        state = {"date_time": "2026-11-20T12:00:00Z", "odometer": "10"}

        def handler(url):
            if url.endswith("rcs/rvs/vehicleStatus"):
                return _JsonResponse(_vehicle_status(date_time=state["date_time"]))
            if "enrollment/details/" in url:
                return _JsonResponse(_enrollment(odometer=state["odometer"]))
            raise AssertionError(f"unexpected URL {url}")

        calls = self._install_get(api, handler)

        first = await api.get_cached_vehicle_status("reg1")
        # The car drives and sends a new status report.
        state["date_time"] = "2026-11-20T13:30:00Z"
        state["odometer"] = "42"
        second = await api.get_cached_vehicle_status("reg1")

        enrollment_calls = [url for url in calls if "enrollment/details/" in url]
        self.assertEqual(len(enrollment_calls), 2)
        self.assertEqual(_mileage(first), "10")
        self.assertEqual(_mileage(second), "42")

    async def test_enrollment_stays_cached_while_status_is_unchanged(self):
        api = _ready_api()

        def handler(url):
            if url.endswith("rcs/rvs/vehicleStatus"):
                return _JsonResponse(_vehicle_status())
            if "enrollment/details/" in url:
                return _JsonResponse(_enrollment())
            raise AssertionError(f"unexpected URL {url}")

        calls = self._install_get(api, handler)

        for _ in range(3):
            await api.get_cached_vehicle_status("reg1")

        enrollment_calls = [url for url in calls if "enrollment/details/" in url]
        self.assertEqual(len(enrollment_calls), 1)

    async def test_failed_enrollment_refresh_keeps_the_cached_copy(self):
        api = _ready_api()
        state = {"date_time": "2026-11-20T12:00:00Z", "fail": False}

        def handler(url):
            if url.endswith("rcs/rvs/vehicleStatus"):
                return _JsonResponse(_vehicle_status(date_time=state["date_time"]))
            if "enrollment/details/" in url:
                if state["fail"]:
                    return ClientError("BlueLink API error: please try again later")
                return _JsonResponse(_enrollment(odometer="10"))
            raise AssertionError(f"unexpected URL {url}")

        self._install_get(api, handler)

        await api.get_cached_vehicle_status("reg1")
        state["date_time"] = "2026-11-20T13:30:00Z"
        state["fail"] = True
        data = await api.get_cached_vehicle_status("reg1")

        self.assertEqual(_mileage(data), "10")

    async def test_pin_error_on_enrollment_refresh_keeps_polling_and_is_not_repeated(self):
        api = _ready_api()
        state = {"date_time": "2026-11-20T12:00:00Z", "pin_locked": False}

        def handler(url):
            if url.endswith("rcs/rvs/vehicleStatus"):
                return _JsonResponse(_vehicle_status(date_time=state["date_time"]))
            if "enrollment/details/" in url:
                if state["pin_locked"]:
                    return PINLockedError(
                        "BlueLink PIN locked: Your PIN has been locked for 5 minutes."
                    )
                return _JsonResponse(_enrollment(odometer="10"))
            raise AssertionError(f"unexpected URL {url}")

        calls = self._install_get(api, handler)

        await api.get_cached_vehicle_status("reg1")
        state["pin_locked"] = True
        state["date_time"] = "2026-11-20T13:30:00Z"
        second = await api.get_cached_vehicle_status("reg1")
        state["date_time"] = "2026-11-20T15:00:00Z"
        third = await api.get_cached_vehicle_status("reg1")

        enrollment_calls = [url for url in calls if "enrollment/details/" in url]
        status_calls = [url for url in calls if url.endswith("rcs/rvs/vehicleStatus")]
        # One good fetch, one that hit the PIN error, then no further requests.
        self.assertEqual(len(enrollment_calls), 2)
        self.assertEqual(len(status_calls), 3)
        self.assertEqual(_mileage(second), "10")
        self.assertEqual(_mileage(third), "10")


if __name__ == "__main__":
    unittest.main()
