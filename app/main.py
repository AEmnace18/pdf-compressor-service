import os
import tempfile
from pathlib import Path

import pikepdf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

APP_NAME = "DILG SDN PDF Compressor"
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024
DEFAULT_ORIGINS = [
    "https://dilgsdn.com",
    "https://www.dilgsdn.com",
    "http://localhost:3000",
    "http://localhost:3001",
]

def parse_allowed_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "")
    if not raw.strip():
        return DEFAULT_ORIGINS
    return [item.strip() for item in raw.split(",") if item.strip()]

app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=[
        "Content-Disposition",
        "x-output-filename",
        "x-original-size",
        "x-output-size",
        "x-percent-saved",
        "x-bytes-saved",
    ],
    max_age=86400,
)


@app.get("/")
def root():
    return {
        "service": APP_NAME,
        "status": "ok",
        "compress_endpoint": "/compress",
        "health_endpoint": "/health",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


def ensure_pdf_name(value: str) -> str:
    cleaned = (value or "compressed-document.pdf").strip()
    cleaned = "".join("-" if c in '\\/:*?"<>|' else c for c in cleaned)
    if not cleaned.lower().endswith(".pdf"):
        cleaned += ".pdf"
    return cleaned


def level_settings(level: str) -> dict:
    level = (level or "recommended").lower()
    if level == "light":
        return {
            "compress_streams": True,
            "recompress_flate": False,
            "linearize": True,
            "object_stream_mode": pikepdf.ObjectStreamMode.generate,
        }
    if level == "strong":
        return {
            "compress_streams": True,
            "recompress_flate": True,
            "linearize": False,
            "object_stream_mode": pikepdf.ObjectStreamMode.generate,
        }
    return {
        "compress_streams": True,
        "recompress_flate": True,
        "linearize": True,
        "object_stream_mode": pikepdf.ObjectStreamMode.generate,
    }


@app.post("/compress")
async def compress_pdf(
    file: UploadFile = File(...),
    filename: str = Form("compressed-document.pdf"),
    level: str = Form("recommended"),
):
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file only.")

    incoming = await file.read()
    if not incoming:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(incoming) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File is too large. Max size is 25 MB.")

    safe_name = ensure_pdf_name(filename)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / "input.pdf"
        output_path = temp_path / safe_name

        input_path.write_bytes(incoming)

        try:
            with pikepdf.open(input_path) as pdf:
                pdf.remove_unreferenced_resources()
                pdf.save(output_path, **level_settings(level))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Compression failed: {exc}") from exc

        if not output_path.exists():
            raise HTTPException(status_code=500, detail="Compression failed: output file was not created.")

        original_size = input_path.stat().st_size
        output_size = output_path.stat().st_size
        bytes_saved = max(original_size - output_size, 0)
        percent_saved = int(round((bytes_saved / original_size) * 100)) if original_size else 0

        headers = {
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "x-output-filename": safe_name,
            "x-original-size": str(original_size),
            "x-output-size": str(output_size),
            "x-percent-saved": str(percent_saved),
            "x-bytes-saved": str(bytes_saved),
            "Cache-Control": "no-store, max-age=0",
        }

        return FileResponse(
            output_path,
            media_type="application/pdf",
            filename=safe_name,
            headers=headers,
        )


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
