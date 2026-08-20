"""Extração de imagens JPG/PNG via RapidOCR."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PIL import Image

from app.to_xlsx.extractors import ExtractionResult

logger = logging.getLogger(__name__)


def extract_image(path: str, engine=None) -> ExtractionResult:
    from rapidocr_onnxruntime import RapidOCR

    ocr = engine or RapidOCR()
    img = Image.open(path).convert("RGB")
    result, _ = ocr(np.array(img))
    lines: list[str] = []
    if result:
        for item in result:
            if item and len(item) >= 2 and isinstance(item[1], str) and item[1].strip():
                lines.append(item[1].strip())

    text = "\n".join(lines)
    logger.info("Imagem OCR: %s linhas de %s", len(lines), Path(path).name)
    return ExtractionResult(
        source_format=Path(path).suffix.lstrip(".").lower() or "image",
        text=text,
        structured=False,
    )
