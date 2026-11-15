from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from umami_api.config import Settings, load_settings
from umami_api.contracts import (
    CONTRACT_VERSION,
    ERROR_RESPONSES,
    ERRORS,
    ErrorDetail,
    ErrorEnvelope,
    HealthResponse,
    ReadinessResponse,
    ResultOrigin,
)
from umami_api.db import Database
from umami_api.errors import ApiError
from umami_api.v1 import router as v1_router

FOUNDATION_PATHS = ("/api/health", "/api/readiness")
MAX_BODY_BYTES = 256 * 1024


def error_response(status: int, headers: dict[str, str] | None = None,
                   code: str | None = None, message: str | None = None) -> JSONResponse:
    status = status if status in ERRORS else 500
    default_code, default_message = ERRORS[status]
    body = ErrorEnvelope(
        schema_version=CONTRACT_VERSION,
        error=ErrorDetail(code=code or default_code, message=message or default_message),
    )
    return JSONResponse(body.model_dump(), status_code=status, headers=headers)


def is_foundation_path(path: str) -> bool:
    return not path.startswith("/api/v1/") and path.startswith("/api/")


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    settings = settings or load_settings()
    environment = settings.environment

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        owned = None
        if application.state.database is None and settings.database_url:
            owned = application.state.database = Database(settings.database_url)
        try:
            yield
        finally:
            if owned is not None:
                owned.dispose()

    application = FastAPI(
        title="Umami Avocado", version="0.1.0", docs_url=None, redoc_url=None,
        openapi_url="/api/openapi.json", redirect_slashes=False, lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.database = database

    @application.middleware("http")
    async def contract_boundary(request: Request, call_next):
        # Foundation operations accept no body/query. Never parse or echo inputs.
        path = request.url.path
        length = request.headers.get("content-length", "0")
        if is_foundation_path(path) and (
            request.scope.get("query_string") or length != "0"
            or "transfer-encoding" in request.headers
        ):
            response = error_response(400)
        elif not length.isdigit() or int(length) > MAX_BODY_BYTES:
            response = error_response(413 if length.isdigit() else 400)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    if settings.cors_origins:
        application.add_middleware(
            CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Bootstrap-Token",
                           "Idempotency-Key"],
            max_age=600,
        )

    @application.exception_handler(ApiError)
    async def domain_error(_request: Request, exc: ApiError):
        return error_response(exc.status, code=exc.code, message=exc.message)

    @application.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        headers = {"Allow": exc.headers["Allow"]} if exc.headers and "Allow" in exc.headers else None
        return error_response(exc.status_code, headers)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _exc: RequestValidationError):
        return error_response(400)

    @application.exception_handler(Exception)
    async def unexpected_error(_request: Request, _exc: Exception):
        return error_response(500, {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @application.get(
        "/api/health", operation_id="get_health", response_model=HealthResponse,
        responses=ERROR_RESPONSES, tags=["foundation"],
    )
    def health() -> HealthResponse:
        return HealthResponse(
            schema_version=CONTRACT_VERSION, status="ok", environment=environment,
            live_lab_orders_enabled=False,
        )

    @application.get(
        "/api/readiness", operation_id="get_readiness", response_model=ReadinessResponse,
        responses=ERROR_RESPONSES, tags=["foundation"],
    )
    def readiness(request: Request) -> ReadinessResponse:
        database = request.app.state.database
        connected = database.ping() if database is not None else False
        status = "foundation-only" if database is None else ("ready" if connected else "degraded")
        return ReadinessResponse(
            schema_version=CONTRACT_VERSION, status=status, live_lab_orders_enabled=False,
            database_connected=connected, artifact_store_connected=False,
        )

    application.include_router(v1_router)

    def build_openapi(routes):
        schema = get_openapi(title=application.title, version=application.version, routes=routes)
        schema["x-contract-version"] = CONTRACT_VERSION
        schema["components"]["schemas"]["ResultOrigin"] = {
            "title": "ResultOrigin", "type": "string",
            "enum": [item.value for item in ResultOrigin],
            "description": "Provenance only. Neither value grants physical authorization.",
        }
        return schema

    def canonical_openapi():
        if application.openapi_schema is None:
            application.openapi_schema = build_openapi(application.routes)
        return application.openapi_schema

    def foundation_openapi():
        """The reviewed subset that the strict UA-002 client generator emits."""
        return build_openapi([route for route in application.routes
                              if getattr(route, "path", None) in FOUNDATION_PATHS])

    application.openapi = canonical_openapi
    application.state.foundation_openapi = foundation_openapi
    return application


app = create_app()
