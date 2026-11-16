"""Errors with a stable code, mapped to an HTTP status at the application edge."""


class DFError(Exception):
    """Base error. ``code`` is stable for clients; ``status`` is the HTTP mapping."""

    code = "internal_error"
    status = 500

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class BadRequest(DFError):
    code = "bad_request"
    status = 400


class Unauthorized(DFError):
    code = "unauthorized"
    status = 401


class Forbidden(DFError):
    code = "forbidden"
    status = 403


class NotFound(DFError):
    code = "not_found"
    status = 404


class Conflict(DFError):
    code = "conflict"
    status = 409


class GatewayUnavailable(DFError):
    """The corpus gateway rejected the call or could not be reached."""

    code = "gateway_unavailable"
    status = 502

    def __init__(self, message: str, gateway_code: int | None = None) -> None:
        super().__init__(message)
        self.gateway_code = gateway_code


class GatewayVersionMismatch(DFError):
    """The gateway speaks a contract version this build does not."""

    code = "gateway_version_mismatch"
    status = 500
