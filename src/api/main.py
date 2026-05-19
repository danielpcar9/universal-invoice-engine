import uuid
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from pydantic import BaseModel

app = FastAPI(title="Universal Invoice Engine")

ALLOWED = {".xml", ".pdf", ".csv", ".xlsx"}
MAX_SIZE = 10 * 1024 * 1024  # 10MB


class IngestResponse(BaseModel):
    invoice_id: str
    filename: str
    size_bytes: int
    status: str
    received_at: datetime


@app.get("/health", tags=["system"])
def health_check():
    return {"status": "ok"}


@app.post("/ap/invoices/ingest", status_code=201, response_model=IngestResponse)
async def ingest_invoice(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(
            415, f"Unsupported format: {ext}. Use: {', '.join(ALLOWED)}"
        )

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(413, f"Maximum {MAX_SIZE / 1024 / 1024:.0f}MB")

    return IngestResponse(
        invoice_id=str(uuid.uuid4()),
        filename=file.filename,
        size_bytes=len(content),
        status="received",
        received_at=datetime.utcnow(),
    )


def dev():
    import uvicorn

    uvicorn.run("src.api.main:app", reload=True)
