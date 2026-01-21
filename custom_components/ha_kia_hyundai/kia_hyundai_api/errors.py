from aiohttp import ClientError


class BaseError(ClientError):
    pass


class RateError(BaseError):
    pass


class AuthError(BaseError):
    pass

class ActionAlreadyInProgressError(BaseError):
    pass
