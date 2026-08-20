"""Parser CNAB 240 — extrato conta corrente (segmento E)."""

from __future__ import annotations

import logging
from pathlib import Path

from app.to_xlsx.extractors import ExtractionResult

logger = logging.getLogger(__name__)


def extract_cnab240(path: str) -> ExtractionResult:
    raw = Path(path).read_bytes()
    text = raw.decode("latin-1", errors="replace")
    records: list[dict] = []

    for line in text.splitlines():
        line = line.rstrip("\r\n")
        if len(line) < 240:
            # padding comum
            line = line.ljust(240)
        if len(line) < 240:
            continue

        # Tipo de registro na posição 8 (1-based) → index 7
        reg_type = line[7:8]
        # Segmento na posição 14 (1-based) → index 13
        segment = line[13:14]

        # Detalhe segmento E (extrato)
        if reg_type == "3" and segment.upper() == "E":
            records.append(_parse_segment_e(line))

    # Fallback: se não achou segmento E, tenta linhas detalhe genéricas
    if not records:
        for line in text.splitlines():
            line = line.rstrip("\r\n").ljust(240)
            if len(line) >= 240 and line[7:8] == "3":
                # tenta extrair data/valor em posições típicas do segmento E
                rec = _parse_segment_e(line)
                if rec.get("descricao") or rec.get("valor"):
                    records.append(rec)

    logger.info("CNAB240: %s lançamentos de %s", len(records), Path(path).name)
    return ExtractionResult(
        source_format="cnab240",
        records=records,
        text="\n".join(
            f"{r.get('data')} | {r.get('descricao')} | {r.get('valor')} | {r.get('tipo')}"
            for r in records
        ),
        structured=bool(records),
    )


def _parse_segment_e(line: str) -> dict:
    # Layout FEBRABAN Extrato Conta Corrente — Segmento E (aproximação estável)
    # Data lançamento: pos 143-150 (1-based) = DDMMAAAA → idx 142:150
    # Valor: pos 151-168 (1-based), 2 decimais → idx 150:168
    # Tipo lançamento (natureza): pos 169 (C/D) em algumas versões — idx 168
    # Histórico / complemento: pos 177-201 ou 202-240 — usamos fatia ampla
    data_raw = line[142:150].strip()
    valor_raw = line[150:168].strip()
    tipo_cd = line[168:169].strip().upper()
    # Nome da empresa / histórico varia; pega trecho descritivo
    descricao = (line[176:240] or line[90:140]).strip()
    documento = line[104:114].strip()  # nº documento aproximado

    data = _fmt_date(data_raw)
    valor = _fmt_amount(valor_raw)
    if tipo_cd == "D":
        tipo = "debito"
        if isinstance(valor, (int, float)) and valor > 0:
            valor = -valor
    elif tipo_cd == "C":
        tipo = "credito"
    else:
        tipo = "debito" if isinstance(valor, (int, float)) and valor < 0 else "credito"

    return {
        "data": data,
        "descricao": descricao,
        "valor": valor,
        "tipo": tipo,
        "documento": documento,
    }


def _fmt_date(raw: str) -> str:
    raw = "".join(c for c in raw if c.isdigit())
    if len(raw) == 8:
        return f"{raw[0:2]}/{raw[2:4]}/{raw[4:8]}"
    return raw


def _fmt_amount(raw: str):
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return ""
    try:
        return int(digits) / 100.0
    except ValueError:
        return raw
