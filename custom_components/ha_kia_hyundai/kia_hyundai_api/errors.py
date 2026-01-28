from aiohttp import ClientError


class BaseError(ClientError):
    pass


class RateError(BaseError):
    pass


class AuthError(BaseError):
    pass


class ActionAlreadyInProgressError(BaseError):
    pass


class PINLockedError(AuthError):
    """Raised when PIN has been locked due to too many failed attempts.
    
    This typically happens when:
    1. Token expired and multiple re-auth attempts failed
    2. Wrong PIN was entered multiple times
    
    The user must wait for the lockout period (typically 60 minutes) before retrying.
    """
    pass


class TokenExpiredError(AuthError):
    """Raised when the access token has expired and needs refresh."""
    pass
