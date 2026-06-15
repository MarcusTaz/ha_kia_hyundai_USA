import json
import logging

from functools import wraps
from aiohttp import ClientError, ClientResponse, ContentTypeError

from .errors import (
    AuthError,
    ActionAlreadyInProgressError,
    HATARemoteVehicleStatusError,
    PINLockedError,
)
from .util import clean_dictionary_for_logging

_LOGGER = logging.getLogger(__name__)


def _is_empty_body(response_text: str | None) -> bool:
    """Return true when the API returned no usable response body."""
    return response_text is None or response_text.strip() == ""


def _is_success_status(response: ClientResponse) -> bool:
    """Return true for HTTP statuses the API uses for successful commands."""
    return 200 <= response.status < 300


def _is_zero_error_code(error_code) -> bool:
    """Return true when BlueLink's errorCode represents success."""
    return str(error_code) in ("0", "200")


def _extract_bluelink_error_message(response_json: dict) -> str:
    """Return the most useful BlueLink error message available."""
    return response_json.get(
        "errorMessage",
        response_json.get("errorSubMessage", "Unknown error"),
    )


def _is_bluelink_auth_error(url: str, error_code) -> bool:
    """Return true when a BlueLink response should trigger reauthentication."""
    # Upstream USA handling maps oauth/token errorCode 502 to auth failure, but
    # vehicle endpoints can also return 502 for backend HATA failures.
    if str(error_code) == "502" and url.endswith("/oauth/token"):
        return True
    return str(error_code) in ("401", "403", "1003", "1005")


def _is_hata_remote_vehicle_status_error(response_json: dict) -> bool:
    """Return true for the USA Genesis HATA remoteVehicleStatus 502 failure."""
    return (
        str(response_json.get("errorCode")) == "502"
        and response_json.get("systemName") == "HATA"
        and response_json.get("functionName") == "remoteVehicleStatus"
    )


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
    """Decorator for Kia API requests with Kia-specific response format handling."""
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

        # Check content type before trying to parse JSON
        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            # API returned non-JSON (likely HTML error page or session expired)
            response_text = await response.text()
            _LOGGER.warning(
                f"API returned non-JSON response (Content-Type: {content_type}). "
                f"First 500 chars: {response_text[:500]}"
            )
            # Treat this as an auth error to trigger session refresh
            raise AuthError(f"API returned non-JSON response (Content-Type: {content_type})")

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
        except ContentTypeError as e:
            # This shouldn't happen now due to the check above, but handle it anyway
            response_text = await response.text()
            _LOGGER.warning(f"ContentTypeError parsing response: {e}. Text: {response_text[:500]}")
            raise AuthError(f"API returned invalid response: {e}")
        except (RuntimeError, KeyError, TypeError) as e:
            response_text = await response.text()
            _LOGGER.debug(f"error: unknown error response {e}, text: {response_text[:500]}")
            raise ClientError(f"unknown error response: {e}")
    return request_with_logging_wrapper


def request_with_logging_bluelink(func):
    """Decorator for Hyundai/Genesis BlueLink API requests with simpler response handling."""
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

        response_text = await response.text()

        # Upstream USA BlueLink behavior: control commands can return HTTP 200
        # with an empty body. Treat that as success instead of trying to parse
        # JSON and surfacing a JSONDecodeError.
        if _is_empty_body(response_text):
            if _is_success_status(response):
                _LOGGER.debug(
                    "BlueLink API returned empty body with HTTP %s for %s; "
                    "treating command as successful",
                    response.status,
                    url,
                )
                return response

            raise ClientError(
                f"BlueLink API error: HTTP {response.status} with empty response"
            )

        if not _is_success_status(response):
            _LOGGER.debug(
                "BlueLink API returned HTTP %s for %s. First 500 chars: %s",
                response.status,
                url,
                response_text[:500],
            )

        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            _LOGGER.warning(
                f"API returned non-JSON response (Content-Type: {content_type}). "
                f"First 500 chars: {response_text[:500]}"
            )
            if response.status in (401, 403):
                raise AuthError(f"API returned non-JSON auth response (HTTP {response.status})")
            raise ClientError(
                f"API returned non-JSON response (HTTP {response.status}, "
                f"Content-Type: {content_type})"
            )

        try:
            response_json = await response.json()
            _LOGGER.debug(
                f"response json:{clean_dictionary_for_logging(response_json)}"
            )

            # BlueLink API error handling - different format than Kia
            # Check for error responses
            if "errorCode" in response_json and not _is_zero_error_code(response_json.get("errorCode")):
                error_msg = _extract_bluelink_error_message(response_json)
                error_code = response_json.get("errorCode")
                _LOGGER.debug(f"BlueLink API error: {error_code} - {error_msg}")

                if _is_hata_remote_vehicle_status_error(response_json):
                    raise HATARemoteVehicleStatusError(f"BlueLink API error: {error_msg}")

                # Check for PIN locked error - this is critical to detect
                error_msg_upper = error_msg.upper() if error_msg else ""
                if "PIN" in error_msg_upper and "LOCKED" in error_msg_upper:
                    _LOGGER.error(f"PIN LOCKED! User must wait before retrying. Error: {error_msg}")
                    raise PINLockedError(f"BlueLink PIN locked: {error_msg}")

                # Auth errors
                if _is_bluelink_auth_error(url, error_code):
                    raise AuthError(f"BlueLink auth error: {error_msg}")

                raise ClientError(f"BlueLink API error: {error_msg}")

            if not _is_success_status(response):
                raise ClientError(f"BlueLink API error: HTTP {response.status}")

            # Success - return response
            return response

        except ContentTypeError as e:
            _LOGGER.warning(f"ContentTypeError parsing response: {e}. Text: {response_text[:500]}")
            raise AuthError(f"API returned invalid response: {e}")
        except json.JSONDecodeError as e:
            _LOGGER.warning(f"JSONDecodeError parsing response: {e}. Text: {response_text[:500]}")
            raise ClientError(f"BlueLink API returned invalid JSON: {e}")
        except (AuthError, ClientError):
            raise
        except Exception as e:
            _LOGGER.debug(f"BlueLink response parsing note: {e}")
            # For BlueLink, if we can't parse specific error format, just return the response
            # The calling code will handle parsing
            return response
    return request_with_logging_wrapper
