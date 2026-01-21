# run with "python3 src/kia_hyundai_api/stub.py"
import logging
import asyncio

from getpass import getpass
from pathlib import Path
import sys

path_root = Path(__file__).parents[2]
sys.path.append(str(path_root))
from src.kia_hyundai_api import UsKia

logger = logging.getLogger("src.kia_hyundai_api")
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
ch.setFormatter(formatter)
logger.addHandler(ch)


async def testing():
    username = input("Username: ")
    password = getpass()
    async def callback (kwargs: dict) -> dict:
        logger.debug(f"callback called with data:{kwargs}")
        if kwargs["stage"] == "input_code":
            return {"otp_code": input("OTP: ")}
        else:
#            return {"notify_type": "EMAIL"}
            return {"notify_type": "SMS"}
    refresh_token = None
    device_id = "xmcCo80mHvfmLsFVuoG08e:8rO1gIatyOQj3G-lbTTzbcvPzs8l0FIzT2cLKtgyvWT3jwc0NCzYwuuzQVpGbZJRUzuc7t9aQud32g8WyXKBJLkFzxlrNSiUo33NH2q4RSLkIhhXr6ZSFm1-FY7sUH23KNB0Cz1k6ULi"
    api: UsKia = UsKia(username=username, password=password, otp_callback=callback, refresh_token=refresh_token, device_id=device_id)
    try:
        logger.debug(f"device_id: {api.device_id}")
        await api.get_vehicles()
        logger.debug(f"vehicles:{api.vehicles}")
        if api.vehicles is None or len(api.vehicles) == 0:
            raise ValueError("No vehicles found")
        vehicle_id = api.vehicles[0]["vehicleIdentifier"]
        logger.debug(await api.get_cached_vehicle_status(vehicle_id=vehicle_id))
        await api.lock(vehicle_id=vehicle_id)
        while await api.check_last_action_finished(vehicle_id=vehicle_id) is False:
            await asyncio.sleep(1)
        await api.unlock(vehicle_id=vehicle_id)
        logger.debug(f"refresh_token: {api.refresh_token}")
    finally:
        await api.api_session.close()


asyncio.run(testing(), debug=True)
