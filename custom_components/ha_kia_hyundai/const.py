"""Constants for Kia/Hyundai US integration."""

from enum import Enum

from homeassistant.const import Platform

DOMAIN: str = "ha_kia_hyundai"
# Legacy - kept for migration
CONF_VEHICLE_ID: str = "vehicle_id"
# New - stores list of vehicle info dicts
CONF_VEHICLES: str = "vehicles"
CONF_OTP_TYPE: str = "otp_type"
CONF_OTP_CODE: str = "otp_code"
CONF_DEVICE_ID: str = "device_id"
CONF_REFRESH_TOKEN: str = "refresh_token"

CONFIG_FLOW_TEMP_VEHICLES: str = "_temp_vehicles"

DEFAULT_SCAN_INTERVAL: int = 10
DELAY_BETWEEN_ACTION_IN_PROGRESS_CHECKING: int = 20
TEMPERATURE_MIN = 62
TEMPERATURE_MAX = 82

# Integration Setting Constants
CONFIG_FLOW_VERSION: int = 5
PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.DEVICE_TRACKER,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Sensor Specific Constants
DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S.%f"

# Seat status mapping: (heatVentType, heatVentLevel) -> display string
# The API returns heatVentType: 0=off, 1=heat, 2=cool
# and heatVentLevel: 1-4 (intensity)
SEAT_STATUS = {
    (0, 0): "Off",
    (0, 1): "Off",
    (1, 4): "High Heat",
    (1, 3): "Medium Heat",
    (1, 2): "Low Heat",
    (1, 1): "Low Heat",
    (2, 4): "High Cool",
    (2, 3): "Medium Cool",
    (2, 2): "Low Cool",
    (2, 1): "Low Cool",
}


class SeatSettings(Enum):
    """Seat heating/cooling settings for climate control.
    
    These values are sent to the API when starting climate with seat settings.
    The kia-hyundai-api uses these values directly in the API request.
    """

    NONE = 0
    HeatHigh = 6
    HeatMedium = 5
    HeatLow = 4
    CoolHigh = 3
    CoolMedium = 2
    CoolLow = 1


STR_TO_SEAT_SETTING = {
    "Off": SeatSettings.NONE,
    "High Heat": SeatSettings.HeatHigh,
    "Medium Heat": SeatSettings.HeatMedium,
    "Low Heat": SeatSettings.HeatLow,
    "High Cool": SeatSettings.CoolHigh,
    "Medium Cool": SeatSettings.CoolMedium,
    "Low Cool": SeatSettings.CoolLow,
}
