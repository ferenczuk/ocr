"""Parser MT940 (SWIFT) simplificado."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.to_xlsx.extractors import ExtractionResult

logger = logging.getLogger(__name__)


def extract_mt940(path: str) -> ExtractionResult:
    text = Path(path).read_bytes().decode("latin-1", errors="replace")
    records: list[dict] = []

    # Separa por statements aproximados
    blocks = re.split(r"(?=:61:)", text)
    for block in blocks:
        if not block.startswith(":61:"):
            continue
        m61 = re.match(
            r":61:(?P<valdate>\d{6})(?P<entrydate>\d{4})?(?P<dc>[CD])"
            r"(?P<funds>[A-Z])?(?P<amount>[\d,\.]+)(?P<rest>.*)",
            block.replace("\n", ""),
            re.DOTALL,
        )
        if not m61:
            # formato com newline
            m61 = re.search(
                r":61:(\d{6})(\d{4})?([CD])([A-Z])?([\d,\.]+)",
                block,
            )
            if not m61:
                continue
            valdate, _entry, dc, _funds, amount = m61.groups()
            rest = block[m61.end() :]
        else:
            valdate = m61.group("valdate")
            dc = m61.group("dc")
            amount = m61.group("amount")
            rest = m61.group("rest")

        m86 = re.search(r":86:(.+?)(?=:\d{2}[A-Z]?:|$)", rest, re.DOTALL)
        descricao = (m86.group(1) if m86 else rest).strip()
        descricao = re.sub(r"\s+", " ", descricao)

        valor = _parse_amount(amount)
        if dc == "D" and isinstance(valor, float):
            valor = -abs(valor)
        elif dc == "C" and isinstance(valor, float):
            valor = abs(valor)

        records.append(
            {
                "data": _fmt_yyymmdd(valdate),
                "descricao": descricao[:500],
                "valor": valor,
                "tipo": "debito" if dc == "D" else "credito",
                "documento": "",
            }
        )

    logger.info("MT940: %s lançamentos de %s", len(records), Path(path).name)
    return ExtractionResult(
        source_format="mt940",
        records=records,
        text=text[:50_000],
        structured=bool(records),
    )


def _parse_amount(raw: str):
    raw = (raw or "").strip().replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return raw


def _fmt_yyymmdd(raw: str) -> str:
    raw = "".join(c for c in raw if c.isdigit())
    if len(raw) == 6:
        yy, mm, dd = raw[0:2], raw[2:4], raw[4:6]
        year = 2000 + int(yy) if int(yy) < 70 else 1900 + int(yy)
        return f"{dd}/{mm}/{year}"
    return raw
