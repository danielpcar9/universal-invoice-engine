import logging
import uuid

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from src.api.routers import invoices, payments, system
from src.services.invoice_service import (
    DuplicateInvoiceError,
    FileTooLargeError,
    InvalidInvoiceError,
    UnsupportedFormatError,
)

logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "module": "%(name)s", "message": "%(message)s"}',
)
logger = logging.getLogger("api")

app = FastAPI(
    title="Universal Invoice Engine",
    version="0.1.0",
    description="PEPPOL-compliant invoice ingestion & SEPA generation API",
)

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# ── Global exception handlers: domain → HTTP ──
@app.exception_handler(UnsupportedFormatError)
async def unsupported_format_handler(request: Request, exc: UnsupportedFormatError):
    return JSONResponse(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        content={"detail": str(exc)},
    )

@app.exception_handler(FileTooLargeError)
async def file_too_large_handler(request: Request, exc: FileTooLargeError):
    return JSONResponse(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        content={"detail": str(exc)},
    )

@app.exception_handler(InvalidInvoiceError)
async def invalid_invoice_handler(request: Request, exc: InvalidInvoiceError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": str(exc)},
    )

@app.exception_handler(DuplicateInvoiceError)
async def duplicate_invoice_handler(request: Request, exc: DuplicateInvoiceError):
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": "Invoice already ingested",
            "raw_hash": exc.raw_hash,
            "existing_invoice_id": exc.existing_invoice_id,
        },
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    client_host = request.client.host if request.client else "unknown"
    logger.warning(
        f"HTTP error: request_id={request_id} path={request.url.path} "
        f"status={exc.status_code} client={client_host} detail={exc.detail}"
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

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