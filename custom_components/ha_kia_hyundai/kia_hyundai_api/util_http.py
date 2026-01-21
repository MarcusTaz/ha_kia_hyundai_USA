import logging

from functools import wraps
from aiohttp import ClientError, ClientResponse

from .errors import AuthError, ActionAlreadyInProgressError
from .util import clean_dictionary_for_logging

_LOGGER = logging.getLogger(__name__)

def request_with_active_session(func):
    @wraps(func)
    async def request_with_active_session_wrapper(*args, **kwargs) -> ClientResponse:
        try:
            return await func(*args, **kwargs)
        except AuthError:
            _LOGGER.debug("got invalid session, attempting to repair and resend")
            self = args[0]
            self.session_id = None
            self.vehicles = None
            self.last_action = None
            response = await func(*args, **kwargs)
            return response

    return request_with_active_session_wrapper


def request_with_logging(func):
    @wraps(func)
    async def request_with_logging_wrapper(*args, **kwargs):
        url = kwargs["url"]
        json_body = kwargs.get("json_body")
        if json_body is not None:
            _LOGGER.debug(
                f"sending {url} request with {clean_dictionary_for_logging(json_body)}"
            )
        else:
            _LOGGER.debug(f"sending {url} request")
        response = await func(*args, **kwargs)
        _LOGGER.debug(
            f"response headers:{clean_dictionary_for_logging(response.headers)}"
        )
        try:
            response_json = await response.json()
            _LOGGER.debug(
                f"response json:{clean_dictionary_for_logging(response_json)}"
            )
            if response_json["status"]["statusCode"] == 0:
                return response
            if (
                response_json["status"]["statusCode"] == 1
                and response_json["status"]["errorType"] == 1
                and (
                    response_json["status"]["errorCode"] == 1003
                    or response_json["status"]["errorCode"] == 1005 # invalid vehicle key for current session
                    or response_json["status"]["errorCode"] == 1037
                    or response_json["status"]["errorCode"] == 1165 # invalid otp code
                )
            ):
                _LOGGER.debug("error: session invalid")
                raise AuthError(f"api error:{response_json['status']['errorMessage']}")
            if (
                response_json["status"]["statusCode"] == 1
                and response_json["status"]["errorType"] == 1
                and (
                    response_json["status"]["errorCode"] == 1001 # We cannot process your request. Please verify that your vehicle's doors, hood and trunk are closed and locked.
                    or response_json["status"]["errorCode"] == 1132 # Please start or move your vehicle. It may be in a low network coverage area or may not have been started in a few days.
                )
            ):
                self = args[0]
                self.last_action = None
                raise ActionAlreadyInProgressError(f"api error:{response_json['status']['errorMessage']}")
            raise ClientError(f"api error:{response_json['status']['errorMessage']}")
        except RuntimeError:
            response_text = await response.text()
            _LOGGER.debug(f"error: unknown error response {response_text}")
            raise ClientError(f"unknown error response {response_text}")
    return request_with_logging_wrapper
