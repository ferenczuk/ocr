"""Extração PDF (todas as páginas) via PyMuPDF4LLM + RapidOCR."""

from __future__ import annotations

import logging
from pathlib import Path

from app.to_xlsx.extractors import ExtractionResult

logger = logging.getLogger(__name__)


def extract_pdf(
    path: str,
    *,
    ocr_dpi: int = 250,
    force_ocr: bool = False,
    ocr_function=None,
) -> ExtractionResult:
    import pymupdf4llm

    kwargs: dict = {
        "pages": None,  # todas as páginas
        "use_ocr": True,
        "force_ocr": force_ocr,
        "ocr_dpi": ocr_dpi,
        "embed_images": False,
        "show_progress": False,
    }
    if ocr_function is not None:
        kwargs["ocr_function"] = ocr_function

    markdown = pymupdf4llm.to_markdown(path, **kwargs)
    if not isinstance(markdown, str):
        markdown = str(markdown or "")

    logger.info("PDF extraído: %s chars de %s", len(markdown), Path(path).name)
    return ExtractionResult(
        source_format="pdf",
        text=markdown.strip(),
        structured=False,
    )
