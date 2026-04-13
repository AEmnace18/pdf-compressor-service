from __future__ import annotations

from io import BytesIO

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from app.compressor import percent_saved, raster_compress_pdf

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024

app = FastAPI(title="PDF Compressor Prototype", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/compress")
async def compress(
    file: UploadFile = File(...),
    level: str = Form("recommended"),
    filename: str = Form("compressed-document.pdf"),
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

    source_bytes = await file.read()
    if len(source_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds the 25 MB limit.")

    try:
        compressed_bytes, stats = raster_compress_pdf(source_bytes, level)
    except Exception as error:  # pragma: no cover - prototype service
        return JSONResponse({"error": f"Compression failed: {error}"}, status_code=500)

    safe_name = filename.strip() or "compressed-document.pdf"
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"

    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name.replace(chr(34), "")}"',
        "Cache-Control": "no-store, max-age=0",
        **stats,
        "x-bytes-saved": str(max(0, len(source_bytes) - len(compressed_bytes))),
        "x-percent-saved": str(percent_saved(len(source_bytes), len(compressed_bytes))),
    }

    return StreamingResponse(
        BytesIO(compressed_bytes),
        media_type="application/pdf",
        headers=headers,
    )
