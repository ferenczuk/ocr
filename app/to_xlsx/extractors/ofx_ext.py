"""Extração OFX / QFX.

Bancos brasileiros (PagBank, Inter, Nubank, etc.) frequentemente geram OFX 1.x
SGML com <LEDGERBAL><BALAMT> vazio. A biblioteca ofxparse, com fail_fast=True
(padrão), levanta OfxParserException("Empty ledger balance") e derruba o
endpoint. Este extrator:

1. Sanitiza saldos vazios;
2. Extrai <STMTTRN> com parser nativo (não depende de LEDGERBAL);
3. Cai no ofxparse (fail_fast=False) só se o nativo não achar lançamentos.
"""

from __future__ import annotations

import logging
import re
from io import BytesIO
from pathlib import Path

from app.to_xlsx.extractors import ExtractionResult

logger = logging.getLogger(__name__)

_STMTTRN_SPLIT = re.compile(r"<STMTTRN>", re.IGNORECASE)
_STMTTRN_END = re.compile(r"</STMTTRN>", re.IGNORECASE)
_TAG_VALUE = re.compile(
    r"<([A-Za-z0-9.]+)>([^<]*)",
    re.IGNORECASE,
)
_EMPTY_BALAMT = re.compile(r"(<BALAMT>)(\s*)(?=<)", re.IGNORECASE)
_EMPTY_BALAMT_XML = re.compile(r"<BALAMT\s*/>", re.IGNORECASE)
_EMPTY_DTASOF = re.compile(r"(<DTASOF>)(\s*)(?=<)", re.IGNORECASE)
_EMPTY_DTASOF_XML = re.compile(r"<DTASOF\s*/>", re.IGNORECASE)


def extract_ofx(path: str) -> ExtractionResult:
    raw = Path(path).read_bytes()
    text = _decode_ofx(raw)
    sanitized = _sanitize_ofx_balances(text)

    records = _parse_stmttrn(sanitized)
    if not records:
        try:
            records = _parse_with_ofxparse(sanitized)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ofxparse falhou (%s); seguindo com parser nativo", exc)

    logger.info("OFX: %s lançamentos de %s", len(records), Path(path).name)
    return ExtractionResult(
        source_format="ofx",
        records=records,
        text=_records_as_text(records) or sanitized[:50_000],
        structured=True,
    )


def _decode_ofx(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    head = raw[:512].decode("ascii", errors="replace").upper()
    if "UTF-8" in head or "UTF8" in head:
        return raw.decode("utf-8", errors="replace")
    if "1252" in head or "ISO-8859-1" in head or "LATIN" in head:
        return raw.decode("cp1252", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _sanitize_ofx_balances(text: str) -> str:
    """Preenche BALAMT/DTASOF vazios para o ofxparse não abortar."""
    text = _EMPTY_BALAMT_XML.sub("<BALAMT>0.00</BALAMT>", text)
    text = _EMPTY_DTASOF_XML.sub("<DTASOF>19700101</DTASOF>", text)
    text = _EMPTY_BALAMT.sub(r"\g<1>0.00\2", text)
    text = _EMPTY_DTASOF.sub(r"\g<1>19700101\2", text)
    return text


def _parse_stmttrn(text: str) -> list[dict]:
    records: list[dict] = []
    parts = _STMTTRN_SPLIT.split(text)
    for part in parts[1:]:
        block = _STMTTRN_END.split(part, maxsplit=1)[0]
        rec = _record_from_stmttrn(block)
        if rec is not None:
            records.append(rec)
    return records


def _record_from_stmttrn(block: str) -> dict | None:
    tags = _tags_from_block(block)
    amount_raw = tags.get("trnamt", "")
    if not amount_raw and not tags.get("fitid") and not tags.get("memo") and not tags.get("name"):
        return None

    valor = _parse_amount(amount_raw)
    ttype = (tags.get("trntype") or "").strip().lower()
    tipo = "credito" if valor >= 0 else "debito"

    name = (tags.get("name") or tags.get("payee") or "").strip()
    memo = (tags.get("memo") or "").strip()
    descricao = name or memo or ttype
    if name and memo and name != memo:
        descricao = f"{name} — {memo}"

    documento = (
        tags.get("fitid")
        or tags.get("checknum")
        or tags.get("refnum")
        or ""
    ).strip()

    return {
        "data": _parse_ofx_date(tags.get("dtposted") or tags.get("dtuser") or ""),
        "descricao": descricao,
        "valor": valor,
        "tipo": tipo,
        "documento": documento,
    }


def _tags_from_block(block: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for match in _TAG_VALUE.finditer(block):
        key = match.group(1).lower()
        value = match.group(2).strip()
        if key not in tags:
            tags[key] = value
    return tags


def _parse_amount(raw: str):
    s = (raw or "").strip()
    if not s:
        return 0.0
    s = s.replace(" ", "").replace("+", "")
    if re.search(r"\.\d{3},", s) or (s.count(".") > 1 and "," in s):
        s = s.replace(".", "").replace(",", ".")
    elif re.search(r",\d{3}\.", s):
        s = s.replace(",", "")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_ofx_date(raw: str) -> str:
    digits = "".join(c for c in (raw or "") if c.isdigit())
    if len(digits) >= 8:
        year, month, day = digits[0:4], digits[4:6], digits[6:8]
        return f"{day}/{month}/{year}"
    return (raw or "").strip()


def _parse_with_ofxparse(text: str) -> list[dict]:
    from ofxparse import OfxParser

    ofx = OfxParser.parse(BytesIO(text.encode("utf-8")), fail_fast=False)
    records: list[dict] = []
    accounts = getattr(ofx, "accounts", None) or []
    if not accounts and getattr(ofx, "account", None):
        accounts = [ofx.account]

    for account in accounts:
        statement = getattr(account, "statement", None)
        transactions = getattr(statement, "transactions", None) or []
        for tx in transactions:
            rec = _record_from_ofxparse_tx(tx)
            if rec is not None:
                records.append(rec)
    return records


def _record_from_ofxparse_tx(tx) -> dict | None:
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

    tipo = "credito" if valor >= 0 else "debito"
    descricao = payee or memo or ttype
    if payee and memo and payee != memo:
        descricao = f"{payee} — {memo}"

    if not descricao and valor == 0.0 and not txid:
        return None

    return {
        "data": dt.strftime("%d/%m/%Y") if dt else "",
        "descricao": descricao,
        "valor": valor,
        "tipo": tipo,
        "documento": txid,
    }


def _records_as_text(records: list[dict]) -> str:
    lines = []
    for r in records:
        lines.append(
            f"{r.get('data','')} | {r.get('descricao','')} | {r.get('valor','')} | "
            f"{r.get('tipo','')} | {r.get('documento','')}"
        )
    return "\n".join(lines)
