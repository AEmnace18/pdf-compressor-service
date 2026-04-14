from __future__ import annotations

import asyncio
import logging
import time
from io import BytesIO

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.compressor import raster_compress_pdf

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024
MAX_CONCURRENT_COMPRESSIONS = 3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="PDF Compressor Prototype", version="0.3.0")

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
        "x-processing-seconds",
    ],
)

compression_slots = asyncio.Semaphore(MAX_CONCURRENT_COMPRESSIONS)


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
    request_started = time.perf_counter()

    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

    source_bytes = await file.read()
    if len(source_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds the 25 MB limit.")

    logger.info(
        "request:start filename=%s level=%s size=%s",
        file.filename,
        level,
        format_bytes(len(source_bytes)),
    )

    try:
        await asyncio.wait_for(compression_slots.acquire(), timeout=0.25)
    except TimeoutError:
        logger.warning("request:busy filename=%s", file.filename)
        raise HTTPException(
            status_code=429,
            detail="Server is busy. Up to 3 PDF compression jobs can run at once. Please try again in a moment.",
        )

    try:
        output_bytes, stats = await run_in_threadpool(raster_compress_pdf, source_bytes, level)
    except Exception as exc:
        logger.exception("request:failed filename=%s", file.filename)
        raise HTTPException(status_code=500, detail=f"Compression failed: {exc}") from exc
    finally:
        compression_slots.release()

    total_seconds = time.perf_counter() - request_started
    logger.info(
        "request:done filename=%s input=%s output=%s total_seconds=%.2f",
        file.filename,
        format_bytes(len(source_bytes)),
        format_bytes(len(output_bytes)),
        total_seconds,
    )

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "x-output-filename": filename,
        "x-original-size": format_bytes(len(source_bytes)),
        "x-output-size": format_bytes(len(output_bytes)),
        "x-percent-saved": str(percent_saved(len(source_bytes), len(output_bytes))),
        "x-effective-stage": stats.get("x-effective-stage", "unknown"),
        "x-processing-seconds": stats.get("x-processing-seconds", f"{total_seconds:.2f}"),
    }

    return StreamingResponse(
        BytesIO(output_bytes),
        media_type="application/pdf",
        headers=headers,
    )
