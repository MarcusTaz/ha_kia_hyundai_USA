"""Kia Hyundai API - Fixed version with working OTP for USA.

This is a fork of kia-hyundai-api with the following fixes:
- Updated API headers to match current Kia iOS app
- Fixed OTP flow to include the complete_login step
- Added tncFlag to login payload
"""

from .const import SeatSettings
from .errors import BaseError, RateError, AuthError
from .us_kia import UsKia

__version__ = "2.0.0"
