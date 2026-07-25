"""Conversor PDF → Markdown via PyMuPDF4LLM (OCR com RapidOCR)."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class DocumentConverter:
    """Converte a 1ª página do PDF em Markdown com PyMuPDF4LLM + RapidOCR."""

    def __init__(self, ocr_dpi: int = 250, force_ocr: bool = False) -> None:
        self.ocr_dpi = ocr_dpi
        self.force_ocr = force_ocr

        logger.info(
            "Inicializando DocumentConverter (ocr_dpi=%s force_ocr=%s)",
            ocr_dpi,
            force_ocr,
        )

        # Garante RapidOCR (não Tesseract) como plugin explícito
        from pymupdf4llm.ocr import rapidocr_api

        self._ocr_function = rapidocr_api.exec_ocr
        # Warm-up leve: importa o motor ONNX uma vez no startup
        import rapidocr_onnxruntime  # noqa: F401

        logger.info("PyMuPDF4LLM + RapidOCR prontos")

    def convert(self, pdf_path: str) -> str:
        import pymupdf4llm

        started = time.perf_counter()
        markdown = pymupdf4llm.to_markdown(
            pdf_path,
            pages=[0],
            use_ocr=True,
            force_ocr=self.force_ocr,
            ocr_dpi=self.ocr_dpi,
            ocr_function=self._ocr_function,
            embed_images=False,
            show_progress=False,
        )
        if not isinstance(markdown, str):
            markdown = str(markdown or "")

        logger.info(
            "Conversão concluída em %.2fs (%s chars)",
            time.perf_counter() - started,
            len(markdown),
        )
        return markdown.strip() + ("\n" if markdown.strip() else "")
