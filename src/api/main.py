import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from src.api.routers import invoices, system

# 1. Structured Logging Configuration (Production-grade observability)
logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "module": "%(name)s", "message": "%(message)s"}',
)
logger = logging.getLogger("api")

app = FastAPI(title="Universal Invoice Engine")


# 2. Centralized Global Exception Handlers (Security & Separation of Concerns)
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    logger.warning(
        f"HTTP error occurred: status_code={exc.status_code} detail={exc.detail}"
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled server exception", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred in the server."},
    )


# 3. Include Routers
app.include_router(system.router)
app.include_router(invoices.router)


def dev():
    """Entry point for `uv run dev`."""
    import uvicorn

    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)

