"""Parser CAMT.053 (ISO 20022 XML)."""

from __future__ import annotations

import logging
from pathlib import Path

from app.to_xlsx.extractors import ExtractionResult

logger = logging.getLogger(__name__)


def extract_camt053(path: str) -> ExtractionResult:
    from lxml import etree

    tree = etree.parse(path)
    root = tree.getroot()
    # Remove namespaces para XPath simples
    for el in root.xpath("//*"):
        if not isinstance(el.tag, str):
            continue
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]

    records: list[dict] = []
    for ntry in root.findall(".//Ntry"):
        amt_el = ntry.find(".//Amt")
        cdt_dbt = (ntry.findtext(".//CdtDbtInd") or "").strip().upper()
        booking = (
            ntry.findtext(".//BookgDt/Dt")
            or ntry.findtext(".//ValDt/Dt")
            or ntry.findtext(".//BookgDt/DtTm")
            or ""
        )
        booking = booking[:10]
        descricao = (
            ntry.findtext(".//AddtlNtryInf")
            or ntry.findtext(".//NtryDtls//Ustrd")
            or ntry.findtext(".//RmtInf/Ustrd")
            or ntry.findtext(".//TxDtls//Ustrd")
            or ""
        ).strip()
        doc = (
            ntry.findtext(".//AcctSvcrRef")
            or ntry.findtext(".//NtryRef")
            or ""
        ).strip()

        try:
            valor = float(amt_el.text) if amt_el is not None and amt_el.text else 0.0
        except ValueError:
            valor = amt_el.text if amt_el is not None else ""

        if cdt_dbt == "DBIT" and isinstance(valor, float):
            valor = -abs(valor)
            tipo = "debito"
        elif cdt_dbt == "CRDT":
            tipo = "credito"
            if isinstance(valor, float):
                valor = abs(valor)
        else:
            tipo = "debito" if isinstance(valor, float) and valor < 0 else "credito"

        data = _iso_to_br(booking)
        records.append(
            {
                "data": data,
                "descricao": descricao,
                "valor": valor,
                "tipo": tipo,
                "documento": doc,
            }
        )

    logger.info("CAMT.053: %s lançamentos de %s", len(records), Path(path).name)
    return ExtractionResult(
        source_format="camt053",
        records=records,
        text=Path(path).read_text(encoding="utf-8", errors="replace")[:50_000],
        structured=bool(records),
    )


def _iso_to_br(iso: str) -> str:
    iso = (iso or "").strip()
    if len(iso) >= 10 and iso[4] == "-" and iso[7] == "-":
        y, m, d = iso[0:4], iso[5:7], iso[8:10]
        return f"{d}/{m}/{y}"
    return iso
