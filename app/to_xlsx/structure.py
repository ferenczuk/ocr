"""Estruturação de registros: schema fixo, custom ou OpenAI."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.to_xlsx import FIXED_COLUMNS
from app.to_xlsx.extractors import ExtractionResult

logger = logging.getLogger(__name__)


class StructureError(Exception):
    """Erro de estruturação (OpenAI / validação)."""


def parse_schema_param(schema: str | None) -> tuple[str, list[str]]:
    """
    Retorna (mode, columns).
    mode: fixed | ia | custom
    """
    if schema is None or not str(schema).strip():
        return "fixed", list(FIXED_COLUMNS)

    raw = str(schema).strip()
    if raw.lower() == "ia":
        return "ia", []

    # Remove colchetes opcionais: [data, descricao, valor]
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    cols = [c.strip().strip("\"'") for c in raw.split(",") if c.strip()]
    if not cols:
        return "fixed", list(FIXED_COLUMNS)
    return "custom", cols


def structure_data(
    extraction: ExtractionResult,
    *,
    schema_mode: str,
    columns: list[str],
    openai_api_key: str,
    openai_model: str,
    openai_timeout: int,
    openai_max_chars: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Retorna (columns, rows)."""
    # Extratores estruturados (OFX, CNAB, etc.) não devem cair na IA só porque
    # vieram 0 lançamentos — devolve planilha vazia com as colunas pedidas.
    if schema_mode == "custom" and extraction.structured:
        rows = [_project_row(r, columns) for r in extraction.records]
        rows = [r for r in rows if _row_has_content(r)]
        return columns, _validate_rows(rows, columns)

    if schema_mode == "fixed" and extraction.structured:
        rows = [_project_row(r, FIXED_COLUMNS) for r in extraction.records]
        rows = [r for r in rows if _row_has_content(r)]
        return list(FIXED_COLUMNS), _validate_rows(rows, FIXED_COLUMNS)

    need_ai = schema_mode == "ia" or not extraction.structured or not extraction.records

    if need_ai:
        if not openai_api_key:
            raise StructureError(
                "OPENAI_API_KEY não configurada — necessária para este arquivo/schema"
            )
        target_cols = None if schema_mode == "ia" else (columns or list(FIXED_COLUMNS))
        return _structure_with_openai(
            extraction,
            target_columns=target_cols,
            api_key=openai_api_key,
            model=openai_model,
            timeout=openai_timeout,
            max_chars=openai_max_chars,
        )

    return list(FIXED_COLUMNS), []


def _project_row(row: dict, columns: list[str]) -> dict[str, Any]:
    lower = {str(k).lower(): v for k, v in row.items()}
    out: dict[str, Any] = {}
    for col in columns:
        out[col] = lower.get(col.lower(), row.get(col, ""))
    return out


def _row_has_content(row: dict) -> bool:
    return any(str(v).strip() for v in row.values() if v is not None)


def _validate_rows(rows: list[dict], columns: list[str]) -> list[dict]:
    cleaned: list[dict] = []
    for row in rows:
        item = {c: row.get(c, "") for c in columns}
        if "valor" in item:
            item["valor"] = _normalize_valor(item["valor"])
        if "data" in item:
            item["data"] = _normalize_data(item["data"])
        if _row_has_content(item):
            cleaned.append(item)
    return cleaned


def _normalize_valor(value: Any) -> Any:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    s = re.sub(r"[R$\s]", "", s)
    if re.match(r"^-?\d{1,3}(\.\d{3})*,\d{2}$", s) or ("," in s and "." in s and s.rfind(",") > s.rfind(".")):
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return value


def _normalize_data(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    # ISO
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        return s
    m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", s)
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return s


def _structure_with_openai(
    extraction: ExtractionResult,
    *,
    target_columns: list[str] | None,
    api_key: str,
    model: str,
    timeout: int,
    max_chars: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    from openai import OpenAI

    text = extraction.text or _records_to_text(extraction.records)
    if not text.strip() and extraction.records:
        text = _records_to_text(extraction.records)
    if not text.strip():
        raise StructureError("Nenhum texto extraído do arquivo para estruturar")

    truncated = False
    if len(text) > max_chars:
        logger.warning(
            "Texto truncado de %s para %s chars antes da OpenAI",
            len(text),
            max_chars,
        )
        text = text[:max_chars]
        truncated = True

    if target_columns:
        cols_instruction = (
            "Use EXATAMENTE estas colunas (chaves JSON): "
            + ", ".join(target_columns)
            + ". Não invente outras colunas."
        )
        columns_out = list(target_columns)
    else:
        cols_instruction = (
            "Infira as colunas mais adequadas para um extrato/documento contábil "
            "(preferir nomes curtos em português: data, descricao, valor, tipo, documento, etc.)."
        )
        columns_out = []

    system = (
        "Você extrai lançamentos financeiros de textos de extratos/documentos contábeis. "
        "Responda APENAS JSON válido no formato: "
        '{"columns":["..."],"rows":[{"col":"valor",...}]}. '
        "Cada row é um objeto com as chaves de columns. "
        "Datas em DD/MM/YYYY. Valores numéricos (ponto decimal). "
        "Não invente lançamentos que não estejam no texto."
    )
    trunc_note = "(texto truncado)\n" if truncated else ""
    user = (
        f"{cols_instruction}\n"
        f"Formato de origem: {extraction.source_format}\n"
        f"{trunc_note}"
        f"--- TEXTO ---\n{text}\n--- FIM ---"
    )

    client = OpenAI(api_key=api_key, timeout=timeout)
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
    except Exception as exc:  # noqa: BLE001
        raise StructureError(f"Falha na OpenAI: {exc}") from exc

    content = resp.choices[0].message.content or "{}"
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise StructureError(f"JSON inválido da OpenAI: {exc}") from exc

    ai_cols = payload.get("columns") or columns_out or list(FIXED_COLUMNS)
    if not isinstance(ai_cols, list) or not ai_cols:
        ai_cols = columns_out or list(FIXED_COLUMNS)
    ai_cols = [str(c).strip() for c in ai_cols if str(c).strip()]

    raw_rows = payload.get("rows") or []
    rows: list[dict] = []
    for r in raw_rows:
        if isinstance(r, dict):
            rows.append(_project_row(r, ai_cols))

    return ai_cols, _validate_rows(rows, ai_cols)


def _records_to_text(records: list[dict]) -> str:
    lines = []
    for r in records:
        lines.append(" | ".join(f"{k}: {v}" for k, v in r.items()))
    return "\n".join(lines)
