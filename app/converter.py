"""Wrapper Marker: converte apenas a 1ª página do PDF para markdown (CPU + OCR)."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class MarkerConverter:
    """Singleton que mantém os modelos Marker carregados em memória."""

    def __init__(self, device: str = "cpu") -> None:
        os.environ["TORCH_DEVICE"] = device

        from marker.config.parser import ConfigParser
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        config: dict[str, Any] = {
            "output_format": "markdown",
            "page_range": "0",
            "force_ocr": True,
            "disable_image_extraction": True,
        }
        config_parser = ConfigParser(config)

        logger.info("Carregando modelos Marker em device=%s ...", device)
        try:
            artifact_dict = create_model_dict(device=device)
        except TypeError:
            artifact_dict = create_model_dict()

        self._converter = PdfConverter(
            config=config_parser.generate_config_dict(),
            artifact_dict=artifact_dict,
            processor_list=config_parser.get_processors(),
            renderer=config_parser.get_renderer(),
        )
        logger.info("Modelos Marker prontos")

    def convert(self, pdf_path: str) -> str:
        from marker.output import text_from_rendered

        rendered = self._converter(pdf_path)
        text, _, _ = text_from_rendered(rendered)
        return text or ""
