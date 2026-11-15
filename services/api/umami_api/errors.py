"""Domain errors with server-authored messages. Request input is never echoed."""


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message[:200]


def not_found(what: str = "resource") -> ApiError:
    return ApiError(404, "not_found", f"The {what} was not found.")


def forbidden(message: str = "The authenticated principal may not perform this action.") -> ApiError:
    return ApiError(403, "forbidden", message)


def conflict(message: str) -> ApiError:
    return ApiError(409, "conflict", message)


def invalid(message: str) -> ApiError:
    return ApiError(400, "invalid_request", message)
