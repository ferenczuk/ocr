"""Orquestra: detectar → extrair → estruturar → xlsx."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.to_xlsx.detect import detect_format
from app.to_xlsx.extractors import ExtractionResult
from app.to_xlsx.extractors.camt053 import extract_camt053
from app.to_xlsx.extractors.cnab240 import extract_cnab240
from app.to_xlsx.extractors.docx_ext import extract_docx
from app.to_xlsx.extractors.image import extract_image
from app.to_xlsx.extractors.mt940 import extract_mt940
from app.to_xlsx.extractors.ofx_ext import extract_ofx
from app.to_xlsx.extractors.pdf import extract_pdf
from app.to_xlsx.extractors.text_csv import extract_text_or_csv
from app.to_xlsx.structure import StructureError, parse_schema_param, structure_data
from app.to_xlsx.workbook import build_xlsx_bytes

logger = logging.getLogger(__name__)


@dataclass
class ToXlsxResult:
    filename: str
    source_format: str
    schema_mode: str
    columns: list[str]
    rows: int
    xlsx_bytes: bytes


class ToXlsxPipeline:
    def __init__(
        self,
        *,
        ocr_dpi: int = 250,
        force_ocr: bool = False,
        openai_api_key: str = "",
        openai_model: str = "gpt-4o-mini",
        openai_timeout: int = 120,
        openai_max_chars: int = 100_000,
        ocr_function=None,
        rapidocr_engine=None,
    ) -> None:
        self.ocr_dpi = ocr_dpi
        self.force_ocr = force_ocr
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.openai_timeout = openai_timeout
        self.openai_max_chars = openai_max_chars
        self.ocr_function = ocr_function
        self.rapidocr_engine = rapidocr_engine

    def run(self, data: bytes, filename: str, schema: str | None = None) -> ToXlsxResult:
        schema_mode, columns = parse_schema_param(schema)
        source_format = detect_format(data, filename)
        logger.info(
            "to-xlsx: file=%s format=%s schema_mode=%s",
            filename,
            source_format,
            schema_mode,
        )

        suffix = Path(filename).suffix or f".{source_format}"
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                tmp_path = Path(tmp.name)

            extraction = self._extract(str(tmp_path), source_format)
            cols, rows = structure_data(
                extraction,
                schema_mode=schema_mode,
                columns=columns,
                openai_api_key=self.openai_api_key,
                openai_model=self.openai_model,
                openai_timeout=self.openai_timeout,
                openai_max_chars=self.openai_max_chars,
            )
            xlsx_bytes = build_xlsx_bytes(cols, rows)
            out_name = f"{Path(filename).stem or 'document'}.xlsx"
            return ToXlsxResult(
                filename=out_name,
                source_format=extraction.source_format or source_format,
                schema_mode=schema_mode,
                columns=cols,
                rows=len(rows),
                xlsx_bytes=xlsx_bytes,
            )
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def _extract(self, path: str, source_format: str) -> ExtractionResult:
        fmt = source_format.lower()
        if fmt == "pdf":
            return extract_pdf(
                path,
                ocr_dpi=self.ocr_dpi,
                force_ocr=self.force_ocr,
                ocr_function=self.ocr_function,
            )
        if fmt in ("jpg", "jpeg", "png", "image"):
            return extract_image(path, engine=self.rapidocr_engine)
        if fmt in ("txt", "csv"):
            return extract_text_or_csv(path, fmt)
        if fmt == "docx":
            return extract_docx(path)
        if fmt in ("ofx", "qfx"):
            return extract_ofx(path)
        if fmt == "cnab240":
            return extract_cnab240(path)
        if fmt == "mt940":
            return extract_mt940(path)
        if fmt == "camt053":
            return extract_camt053(path)

        # Fallback: tenta ler como texto e deixa a IA estruturar
        logger.warning("Formato %s sem extrator dedicado — fallback texto", fmt)
        try:
            return extract_text_or_csv(path, "txt")
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Formato não suportado: {fmt}") from exc


__all__ = ["ToXlsxPipeline", "ToXlsxResult", "StructureError"]
