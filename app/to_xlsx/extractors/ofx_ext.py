"""Extração OFX / QFX."""

from __future__ import annotations

import logging
from pathlib import Path

from app.to_xlsx.extractors import ExtractionResult

logger = logging.getLogger(__name__)


def extract_ofx(path: str) -> ExtractionResult:
    from ofxparse import OfxParser

    with open(path, "rb") as fh:
        ofx = OfxParser.parse(fh)

    records: list[dict] = []
    accounts = getattr(ofx, "accounts", None) or []
    if not accounts and getattr(ofx, "account", None):
        accounts = [ofx.account]

    for account in accounts:
        statement = getattr(account, "statement", None)
        transactions = getattr(statement, "transactions", None) or []
        for tx in transactions:
            dt = getattr(tx, "date", None)
            amount = getattr(tx, "amount", None)
            memo = (getattr(tx, "memo", None) or "").strip()
            payee = (getattr(tx, "payee", None) or "").strip()
            txid = (getattr(tx, "id", None) or "").strip()
            ttype = (getattr(tx, "type", None) or "").strip()

            try:
                valor = float(amount) if amount is not None else 0.0
            except (TypeError, ValueError):
                valor = 0.0

            tipo = ttype.lower() if ttype else ("credito" if valor >= 0 else "debito")
            descricao = payee or memo or ttype
            if payee and memo and payee != memo:
                descricao = f"{payee} — {memo}"

            records.append(
                {
                    "data": dt.strftime("%d/%m/%Y") if dt else "",
                    "descricao": descricao,
                    "valor": valor,
                    "tipo": tipo,
                    "documento": txid,
                }
            )

    logger.info("OFX: %s lançamentos de %s", len(records), Path(path).name)
    return ExtractionResult(
        source_format="ofx",
        records=records,
        text=_records_as_text(records),
        structured=True,
    )


def _records_as_text(records: list[dict]) -> str:
    lines = []
    for r in records:
        lines.append(
            f"{r.get('data','')} | {r.get('descricao','')} | {r.get('valor','')} | "
            f"{r.get('tipo','')} | {r.get('documento','')}"
        )
    return "\n".join(lines)
