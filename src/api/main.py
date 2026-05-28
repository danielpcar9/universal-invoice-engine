import logging
import uuid


from dataclasses import dataclass
from typing import Callable, Any
from sqlalchemy.exc import (
    SQLAlchemyError,
    IntegrityError,
    OperationalError,
    ProgrammingError,
)
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from fastapi.security import APIKeyHeader

from src.api.logging import setup_logging, request_id_var

from src.api.routers import invoices, payments, system
from src.services.invoice_service import (
    DuplicateInvoiceError,
    FileTooLargeError,
    InvalidInvoiceError,
    MissingFilenameError,
    UnsupportedFormatError,
)
from src.services.sepa_payment_service import (
    InvoiceNotFoundError,
    MissingIbanError,
    SepaPaymentServiceError,
)

setup_logging()
logger = logging.getLogger("api")

app = FastAPI(
    title="Universal Invoice Engine",
    version="0.1.0",
    description="PEPPOL-compliant invoice ingestion & SEPA generation API",
)

# OpenAPI: declare API Key security scheme so the docs show `X-API-Key`
API_KEY_NAME = "X-API-Key"
api_key_scheme = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    components = openapi_schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes.setdefault(
        "ApiKeyAuth",
        {
            "type": "apiKey",
            "in": "header",
            "name": API_KEY_NAME,
        },
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    # propagate to logging contextvars so all logs automatically include request_id
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_var.reset(token)


@dataclass(frozen=True)
class ErrorMapping:
    status_code: int
    response_factory: Callable[[Any], dict[str, Any]] | None = None


# Declarative exception mapping: domain exception class -> ErrorMapping
_DOMAIN_ERROR_CONFIG: dict[type[Exception], ErrorMapping] = {
    UnsupportedFormatError: ErrorMapping(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE),
    FileTooLargeError:      ErrorMapping(status_code=status.HTTP_413_CONTENT_TOO_LARGE),
    InvalidInvoiceError:    ErrorMapping(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT),
    MissingFilenameError:   ErrorMapping(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT),
    MissingIbanError:       ErrorMapping(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT),
    InvoiceNotFoundError:   ErrorMapping(status_code=status.HTTP_404_NOT_FOUND),
    SepaPaymentServiceError: ErrorMapping(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT),
    DuplicateInvoiceError:  ErrorMapping(
        status_code=status.HTTP_409_CONFLICT,
        response_factory=lambda exc: {
            "detail": "Invoice already ingested",
            "raw_hash": exc.raw_hash,
            "existing_invoice_id": str(exc.existing_invoice_id)
            if exc.existing_invoice_id
            else None,
        },
    ),
}


def _make_domain_handler(mapping: ErrorMapping):
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        if mapping.response_factory:
            content = mapping.response_factory(exc)
        else:
            content = {"detail": str(exc)}
        return JSONResponse(status_code=mapping.status_code, content=content)

    return handler


for _exc_cls, _mapping in _DOMAIN_ERROR_CONFIG.items():
    app.add_exception_handler(_exc_cls, _make_domain_handler(_mapping))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    client_host = request.client.host if request.client else "unknown"
    logger.warning(
        f"HTTP error: request_id={request_id} path={request.url.path} "
        f"status={exc.status_code} client={client_host} detail={exc.detail}"
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(IntegrityError)
async def integrity_exception_handler(
    request: Request, exc: IntegrityError
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    client_host = request.client.host if request.client else "unknown"
    logger.warning(
        f"Database integrity constraint violation: request_id={request_id} "
        f"path={request.url.path} client={client_host}",
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "Database integrity constraint violation."},
    )


@app.exception_handler(OperationalError)
async def operational_exception_handler(
    request: Request, exc: OperationalError
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    client_host = request.client.host if request.client else "unknown"
    logger.error(
        f"Database operational error (possible connection issue): request_id={request_id} "
        f"path={request.url.path} client={client_host}",
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Database service is temporarily unavailable."},
    )


@app.exception_handler(ProgrammingError)
async def programming_exception_handler(
    request: Request, exc: ProgrammingError
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    client_host = request.client.host if request.client else "unknown"
    logger.error(
        f"Database programming error (query bug/schema mismatch): request_id={request_id} "
        f"path={request.url.path} client={client_host}",
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "A database configuration or query error occurred."},
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(
    request: Request, exc: SQLAlchemyError
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    client_host = request.client.host if request.client else "unknown"
    logger.error(
        f"General database error: request_id={request_id} path={request.url.path} client={client_host}",
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "A database error occurred."},
    )


# ── Unhandled / Catch-all Exception: Observability Only ──
# This handler acts as a final safety net, primarily for logging and telemetry/Sentry.
# It does not perform control flow or business logic parsing.
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    client_host = request.client.host if request.client else "unknown"
    logger.error(
        f"Unhandled server exception: request_id={request_id} path={request.url.path} "
        f"client={client_host}",
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred in the server."},
    )


app.include_router(system.router, prefix="/api/v1")
app.include_router(invoices.router, prefix="/api/v1")
app.include_router(payments.router, prefix="/api/v1")


def dev():
    import uvicorn

    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
