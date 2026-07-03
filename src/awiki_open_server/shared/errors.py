from __future__ import annotations


class AwikiError(Exception):
    code = -32000
    message = "server_error"

    def __init__(self, message: str | None = None, *, data: dict | None = None):
        super().__init__(message or self.message)
        self.error_message = message or self.message
        self.data = data or {}


class InvalidRequest(AwikiError):
    code = -32600
    message = "invalid_request"


class MethodNotFound(AwikiError):
    code = -32601
    message = "method_not_found"


class InvalidParams(AwikiError):
    code = -32602
    message = "invalid_params"


class Unauthorized(AwikiError):
    code = -32001
    message = "unauthorized"


class NotSupported(AwikiError):
    code = -32010
    message = "not_supported"


class NotFound(AwikiError):
    code = -32004
    message = "not_found"


class Conflict(AwikiError):
    code = -32009
    message = "conflict"
