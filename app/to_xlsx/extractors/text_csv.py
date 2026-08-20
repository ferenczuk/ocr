"""Extração TXT / CSV."""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path

from app.to_xlsx.extractors import ExtractionResult

logger = logging.getLogger(__name__)


def extract_text_or_csv(path: str, source_format: str) -> ExtractionResult:
    raw = Path(path).read_bytes()
    text = _decode(raw)

    if source_format == "csv" or _looks_like_csv(text):
        records = _parse_csv(text)
        if records:
            logger.info("CSV: %s linhas", len(records))
            return ExtractionResult(
                source_format="csv",
                records=records,
                text=text,
                structured=True,
            )

    return ExtractionResult(
        source_format="txt",
        text=text.strip(),
        structured=False,
    )


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _looks_like_csv(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    return lines[0].count(";") >= 2 or lines[0].count(",") >= 2


def _parse_csv(text: str) -> list[dict]:
    sample = text[:4096]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        return []
    rows: list[dict] = []
    for row in reader:
        cleaned = {
            (k or "").strip(): (v or "").strip()
            for k, v in row.items()
            if k is not None
        }
        if any(cleaned.values()):
            rows.append(_normalize_csv_row(cleaned))
    return rows


def _normalize_csv_row(row: dict) -> dict:
    """Mapeia cabeçalhos comuns → schema fixo parcial."""
    lower = {k.lower().strip(): v for k, v in row.items()}
    mapping = {
        "data": ("data", "date", "dt", "data_lancamento", "data lançamento", "dt_lanc"),
        "descricao": (
            "descricao",
            "descrição",
            "description",
            "historico",
            "histórico",
            "memo",
            "nome",
            "lançamento",
            "lancamento",
        ),
        "valor": ("valor", "amount", "value", "vlr", "montante"),
        "tipo": ("tipo", "type", "natureza", "d/c", "dc", "credito_debito"),
        "documento": (
            "documento",
            "document",
            "cpf",
            "cnpj",
            "doc",
            "numero",
            "número",
            "fitid",
        ),
    }
    out: dict = {}
    for target, aliases in mapping.items():
        for alias in aliases:
            if alias in lower and lower[alias]:
                out[target] = lower[alias]
                break
    # Se não mapeou quase nada, guarda o row bruto no text-friendly
    if len(out) < 2:
        out = {
            "data": "",
            "descricao": " | ".join(f"{k}: {v}" for k, v in row.items() if v),
            "valor": "",
            "tipo": "",
            "documento": "",
        }
    return out
