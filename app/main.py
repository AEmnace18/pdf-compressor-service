from __future__ import annotations

from io import BytesIO

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.compressor import raster_compress_pdf

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024

app = FastAPI(title="PDF Compressor Prototype", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://dilgsdnworksite.vercel.app",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=[
        "x-output-filename",
        "x-original-size",
        "x-output-size",
        "x-percent-saved",
        "x-effective-stage",
    ],
)


def format_bytes(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def percent_saved(before: int, after: int) -> int:
    if before <= 0:
        return 0
    return max(0, round(((before - after) / before) * 100))


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

    output_bytes, stats = raster_compress_pdf(source_bytes, level)

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "x-output-filename": filename,
        "x-original-size": format_bytes(len(source_bytes)),
        "x-output-size": format_bytes(len(output_bytes)),
        "x-percent-saved": str(percent_saved(len(source_bytes), len(output_bytes))),
        "x-effective-stage": stats.get("x-effective-stage", "unknown"),
    }

    return StreamingResponse(
        BytesIO(output_bytes),
        media_type="application/pdf",
        headers=headers,
    )
