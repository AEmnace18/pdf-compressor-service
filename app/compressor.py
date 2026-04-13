from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Iterable, Literal

import pypdfium2 as pdfium
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

CompressionLevel = Literal["light", "recommended", "strong"]


@dataclass(frozen=True)
class CompressionPreset:
    dpi: int
    jpeg_quality: int
    grayscale: bool
    optimize: bool = False
    progressive: bool = False


PRESETS: dict[CompressionLevel, CompressionPreset] = {
    "light": CompressionPreset(dpi=150, jpeg_quality=68, grayscale=False),
    "recommended": CompressionPreset(dpi=110, jpeg_quality=46, grayscale=False),
    "strong": CompressionPreset(dpi=90, jpeg_quality=30, grayscale=True),
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
    working.save(
        encoded,
        format="JPEG",
        quality=preset.jpeg_quality,
        optimize=preset.optimize,
        progressive=preset.progressive,
    )
    return encoded.getvalue()


def _render_pages(source_bytes: bytes, preset: CompressionPreset) -> Iterable[tuple[bytes, float, float]]:
    pdf = pdfium.PdfDocument(BytesIO(source_bytes))
    scale = preset.dpi / 72.0

    try:
        for index in range(len(pdf)):
            page = pdf[index]
            bitmap = page.render(scale=scale)
            try:
                pil_image = bitmap.to_pil()
                page_width_px, page_height_px = pil_image.size
                page_width_points = (page_width_px / preset.dpi) * 72.0
                page_height_points = (page_height_px / preset.dpi) * 72.0
                yield _encode_page_image(pil_image, preset), page_width_points, page_height_points
            finally:
                page.close()
    finally:
        pdf.close()


def raster_compress_pdf(source_bytes: bytes, level: str) -> tuple[bytes, dict[str, str]]:
    preset = get_preset(level)
    output = BytesIO()
    pdf_canvas: canvas.Canvas | None = None

    for page_jpeg, width_points, height_points in _render_pages(source_bytes, preset):
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

    if pdf_canvas is None:
        raise ValueError("The PDF appears to have no pages.")

    pdf_canvas.save()
    result_bytes = output.getvalue()
    stats = {
        "x-original-size": format_bytes(len(source_bytes)),
        "x-output-size": format_bytes(len(result_bytes)),
        "x-percent-saved": str(percent_saved(len(source_bytes), len(result_bytes))),
        "x-effective-stage": f"raster-fast-{get_preset(level)}",
    }
    return result_bytes, stats
