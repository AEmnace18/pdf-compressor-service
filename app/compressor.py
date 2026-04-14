from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Iterable, Literal

import pypdfium2 as pdfium
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)

CompressionLevel = Literal["light", "recommended", "strong"]


@dataclass(frozen=True)
class CompressionPreset:
    dpi: int
    jpeg_quality: int
    grayscale: bool
    optimize: bool = False
    progressive: bool = False


PRESETS: dict[CompressionLevel, CompressionPreset] = {
    "light": CompressionPreset(dpi=120, jpeg_quality=62, grayscale=False),
    "recommended": CompressionPreset(dpi=96, jpeg_quality=40, grayscale=False),
    "strong": CompressionPreset(dpi=72, jpeg_quality=28, grayscale=True),
}


def get_preset(level: str) -> CompressionPreset:
    normalized = level.lower().strip()
    if normalized in PRESETS:
        return PRESETS[normalized]  # type: ignore[index]
    return PRESETS["recommended"]


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


def _encode_page_image(image: Image.Image, preset: CompressionPreset) -> bytes:
    working = image.convert("L") if preset.grayscale else image.convert("RGB")
    encoded = BytesIO()
    try:
        working.save(
            encoded,
            format="JPEG",
            quality=preset.jpeg_quality,
            optimize=preset.optimize,
            progressive=preset.progressive,
        )
        return encoded.getvalue()
    finally:
        working.close()


def _render_pages(
    source_bytes: bytes, preset: CompressionPreset
) -> Iterable[tuple[bytes, float, float, int, int]]:
    pdf = pdfium.PdfDocument(BytesIO(source_bytes))
    scale = preset.dpi / 72.0
    total_pages = len(pdf)

    logger.info(
        "compress:start pages=%s dpi=%s quality=%s grayscale=%s",
        total_pages,
        preset.dpi,
        preset.jpeg_quality,
        preset.grayscale,
    )

    try:
        for index in range(total_pages):
            page = pdf[index]
            bitmap = None
            pil_image = None
            try:
                t0 = time.perf_counter()
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()

                page_width_px, page_height_px = pil_image.size
                page_width_points = (page_width_px / preset.dpi) * 72.0
                page_height_points = (page_height_px / preset.dpi) * 72.0

                encoded = _encode_page_image(pil_image, preset)
                elapsed = time.perf_counter() - t0
                logger.info(
                    "compress:page_done page=%s/%s render_seconds=%.2f jpeg_bytes=%s",
                    index + 1,
                    total_pages,
                    elapsed,
                    len(encoded),
                )
                yield encoded, page_width_points, page_height_points, index + 1, total_pages
            finally:
                try:
                    if pil_image is not None:
                        pil_image.close()
                except Exception:
                    pass

                try:
                    if bitmap is not None and hasattr(bitmap, "close"):
                        bitmap.close()
                except Exception:
                    pass

                try:
                    if hasattr(page, "close"):
                        page.close()
                except Exception:
                    pass
    finally:
        pdf.close()


def raster_compress_pdf(source_bytes: bytes, level: str) -> tuple[bytes, dict[str, str]]:
    preset = get_preset(level)
    output = BytesIO()
    pdf_canvas: canvas.Canvas | None = None
    page_count = 0
    started = time.perf_counter()

    for page_jpeg, width_points, height_points, page_no, total_pages in _render_pages(source_bytes, preset):
        if pdf_canvas is None:
            pdf_canvas = canvas.Canvas(output, pagesize=(width_points, height_points), pageCompression=1)

        pdf_canvas.setPageSize((width_points, height_points))
        pdf_canvas.drawImage(
            ImageReader(BytesIO(page_jpeg)),
            0,
            0,
            width=width_points,
            height=height_points,
            preserveAspectRatio=False,
            mask="auto",
        )
        pdf_canvas.showPage()
        page_count = page_no
        logger.info("compress:pdf_written page=%s/%s", page_no, total_pages)

    if pdf_canvas is None:
        raise ValueError("The PDF appears to have no pages.")

    pdf_canvas.save()
    result_bytes = output.getvalue()
    total_seconds = time.perf_counter() - started

    logger.info(
        "compress:done pages=%s input=%s output=%s saved=%s%% total_seconds=%.2f",
        page_count,
        len(source_bytes),
        len(result_bytes),
        percent_saved(len(source_bytes), len(result_bytes)),
        total_seconds,
    )

    stats = {
        "x-original-size": format_bytes(len(source_bytes)),
        "x-output-size": format_bytes(len(result_bytes)),
        "x-percent-saved": str(percent_saved(len(source_bytes), len(result_bytes))),
        "x-effective-stage": f"raster-fast-{preset.dpi}dpi-q{preset.jpeg_quality}",
        "x-processing-seconds": f"{total_seconds:.2f}",
    }
    return result_bytes, stats
