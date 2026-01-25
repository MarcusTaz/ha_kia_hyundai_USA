"""Kia Hyundai API - Fixed version with working OTP for USA.

This is a fork of kia-hyundai-api with the following fixes:
- Updated API headers to match current Kia iOS app (appversion 7.22.0, iOS secretkey)
- Fixed OTP flow to include the _complete_login_with_otp step after OTP verification
- Added tncFlag to login payload
- Fixed xid handling during OTP flow
"""

from .const import SeatSettings
from .errors import BaseError, RateError, AuthError
from .us_kia import UsKia

__all__ = ["UsKia", "SeatSettings", "BaseError", "RateError", "AuthError"]
__version__ = "2.0.0"
