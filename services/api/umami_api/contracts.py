"""Versioned public contracts. These types confer no laboratory authority."""
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CONTRACT_VERSION = "1.0"


class ResultOrigin(str, Enum):
    """Permanent provenance labels, never an approval or a conversion operation."""
    SIMULATED = "SIMULATED"
    PHYSICAL = "PHYSICAL"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class FoundationResponse(ContractModel):
    schema_version: Literal["1.0"]
    live_lab_orders_enabled: Literal[False]

    @field_validator("live_lab_orders_enabled", mode="before")
    @classmethod
    def laboratory_dispatch_is_unavailable(cls, value: object) -> object:
        if value is not False:
            raise ValueError("Laboratory dispatch is unavailable in this contract.")
        return value


class HealthResponse(FoundationResponse):
    status: Literal["ok"]
    environment: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")


class ReadinessResponse(FoundationResponse):
    """foundation-only: no database configured; ready: database reachable and migrated;
    degraded: a database is configured but unreachable. Artifact storage (UA-015) is
    available whenever its backing store (PostgreSQL by default) is reachable."""
    status: Literal["foundation-only", "ready", "degraded"]
    database_connected: bool
    artifact_store_connected: bool


class ErrorDetail(ContractModel):
    code: Literal[
        "invalid_request", "unauthorized", "forbidden", "not_found", "method_not_allowed",
        "conflict", "payload_too_large", "policy_denied", "limit_exceeded", "internal_error",
        "unavailable",
    ]
    message: str = Field(min_length=1, max_length=200)


class ErrorEnvelope(ContractModel):
    schema_version: Literal["1.0"]
    error: ErrorDetail


FOUNDATION_ERRORS = {
    400: ("invalid_request", "The request does not match the API contract."),
    404: ("not_found", "The API resource was not found."),
    405: ("method_not_allowed", "The HTTP method is not supported for this resource."),
    500: ("internal_error", "The service could not complete the request."),
}

ERRORS = {
    **FOUNDATION_ERRORS,
    401: ("unauthorized", "A valid bearer token is required."),
    403: ("forbidden", "The authenticated principal may not perform this action."),
    409: ("conflict", "The request conflicts with the current resource state."),
    413: ("payload_too_large", "The request body is too large."),
    503: ("unavailable", "The service dependency is not configured or not reachable."),
}

ERROR_RESPONSES = {
    status: {"model": ErrorEnvelope, "description": message, "x-error-code": code}
    for status, (code, message) in FOUNDATION_ERRORS.items()
}
