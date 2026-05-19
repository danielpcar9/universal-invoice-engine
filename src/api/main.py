import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# 1. Structured Logging Configuration (Production-grade observability)
logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "module": "%(name)s", "message": "%(message)s"}'
)
logger = logging.getLogger("api")

app = FastAPI(title="Universal Invoice Engine")

# Ingestion configuration limits and allowed formats
ALLOWED_EXTENSIONS = {".xml", ".pdf", ".csv", ".xlsx"}
MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10MB


# 2. Pydantic Models (Canonical Request/Response)
class InvoiceIngestResponse(BaseModel):
    invoice_id: str
    filename: str
    size_bytes: int
    status: str
    received_at: datetime


# 3. Centralized Global Exception Handlers (Security & Separation of Concerns)
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    logger.warning(f"HTTP error occurred: status_code={exc.status_code} detail={exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled server exception", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred in the server."}
    )


# 4. API Routes
@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/ap/invoices/ingest",
    status_code=status.HTTP_201_CREATED,
    tags=["invoices"]
)
async def ingest_invoice(
    file: Annotated[
        UploadFile, 
        File(description="The invoice file to ingest (.xml, .pdf, .csv, .xlsx)")
    ]
) -> InvoiceIngestResponse:
    ext = Path(file.filename).suffix.lower()
    
    # 1. Strictly validate the file extension (Semantic 415 error)
    if ext not in ALLOWED_EXTENSIONS:
        logger.warning(f"Rejected file {file.filename}: unsupported format {ext}")
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported format: {ext}. Allowed formats: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    content = await file.read()
    
    # 2. Strictly validate the payload size (Semantic 413 error)
    if len(content) > MAX_SIZE_BYTES:
        logger.warning(f"Rejected file {file.filename}: file size exceeds 10MB limit ({len(content)} bytes)")
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Maximum allowed size is 10MB. Got {len(content) / 1024 / 1024:.2f}MB"
        )
    
    # 3. Generate tracking UUID v4 for end-to-end traceability
    invoice_id = str(uuid.uuid4())
    logger.info(f"Successfully ingested invoice {file.filename} with ID: {invoice_id}")
    
    return InvoiceIngestResponse(
        invoice_id=invoice_id,
        filename=file.filename,
        size_bytes=len(content),
        status="received",
        received_at=datetime.now(timezone.utc)  # Timezone-aware UTC datetime (Python 3.12+ best practice)
    )


def dev():
    """Entry point for `uv run dev`."""
    import uvicorn
    uvicorn.run("src.api.main:app", reload=True)
