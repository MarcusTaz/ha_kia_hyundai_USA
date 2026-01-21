# Configuration Constants
from enum import IntEnum

from homeassistant.const import Platform

DOMAIN: str = "ha_kia_hyundai"
CONF_VEHICLE_ID: str = "vehicle_id"
CONF_OTP_TYPE: str = "otp_type"
CONF_OTP_CODE: str = "otp_code"
CONF_DEVICE_ID: str = "device_id"
CONF_REFRESH_TOKEN: str = "refresh_token"
CONF_ACCESS_TOKEN: str = "access_token"
CONF_BRAND: str = "brand"
CONF_PIN: str = "pin"

CONFIG_FLOW_TEMP_VEHICLES: str = "vehicles"

DEFAULT_SCAN_INTERVAL: int = 10
DELAY_BETWEEN_ACTION_IN_PROGRESS_CHECKING: int = 20
TEMPERATURE_MIN = 62
TEMPERATURE_MAX = 82

# Integration Setting Constants
CONFIG_FLOW_VERSION: int = 4  # Bump version for EU library migration
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

# EU Library seat status values (different from old US library)
# The EU library uses integer values for seat heating/cooling
# 0 = Off, positive = heat level, negative = cool level (varies by vehicle)
# We map the raw seat status tuple (mode, level) to string descriptions
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


class SeatSettings(IntEnum):
    """Seat heating/cooling settings for climate control.

    These match the EU library's expected integer values for seat settings.
    """

    NONE = 0
    HeatLow = 1
    HeatMedium = 2
    HeatHigh = 3
    CoolLow = -1
    CoolMedium = -2
    CoolHigh = -3


STR_TO_SEAT_SETTING = {
    "Off": SeatSettings.NONE,
    "High Heat": SeatSettings.HeatHigh,
    "Medium Heat": SeatSettings.HeatMedium,
    "Low Heat": SeatSettings.HeatLow,
    "High Cool": SeatSettings.CoolHigh,
    "Medium Cool": SeatSettings.CoolMedium,
    "Low Cool": SeatSettings.CoolLow,
}

# Brand constants matching EU library
BRAND_KIA = 1
BRAND_HYUNDAI = 2
BRAND_GENESIS = 3

BRANDS = {
    "Kia": BRAND_KIA,
    "Hyundai": BRAND_HYUNDAI,
    "Genesis": BRAND_GENESIS,
}

# Region constant for USA
REGION_USA = 3
