"""Constants for the Kia Hyundai API."""

from enum import Enum

SENSITIVE_FIELD_NAMES = [
    "username",
    "password",
    "userid",
    "vin",
    "sid",
    "vinkey",
    "lat",
    "lon",
]

# Updated to match current Kia iOS app
API_URL_HOST = "api.owners.kia.com"
API_URL_BASE = "https://" + API_URL_HOST + "/apigw/v1/"


class SeatSettings(Enum):
    """Class to hold seat settings."""

    NONE = 0
    HeatHigh = 6
    HeatMedium = 5
    HeatLow = 4
    CoolHigh = 3
    CoolMedium = 2
    CoolLow = 1
