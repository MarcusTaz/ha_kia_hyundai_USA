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
    "blueLinkServicePin",
    "accessToken",
]

# Kia USA API (iOS app headers)
API_URL_HOST = "api.owners.kia.com"
API_URL_BASE = "https://" + API_URL_HOST + "/apigw/v1/"

# Hyundai USA API (BlueLink)
HYUNDAI_API_URL_HOST = "api.telematics.hyundaiusa.com"
HYUNDAI_LOGIN_API_BASE = "https://" + HYUNDAI_API_URL_HOST + "/v2/ac/"
HYUNDAI_API_URL_BASE = "https://" + HYUNDAI_API_URL_HOST + "/ac/v2/"

# Genesis USA API (connected services)
GENESIS_API_URL_HOST = "api.telematics.genesis.com"
GENESIS_LOGIN_API_BASE = "https://" + GENESIS_API_URL_HOST + "/v2/ac/"
GENESIS_API_URL_BASE = "https://" + GENESIS_API_URL_HOST + "/ac/v2/"


class SeatSettings(Enum):
    """Class to hold seat settings."""

    NONE = 0
    HeatHigh = 6
    HeatMedium = 5
    HeatLow = 4
    CoolHigh = 3
    CoolMedium = 2
    CoolLow = 1
