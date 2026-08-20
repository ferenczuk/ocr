"""Detecção de formato por magic bytes + extensão."""

from __future__ import annotations

import re
from pathlib import Path


def detect_format(data: bytes, filename: str = "") -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    head = data[:8192]
    text_head = ""
    try:
        text_head = head.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        text_head = ""
    text_upper = text_head.upper()

    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"PK") and ext in ("docx", "xlsx"):
        return "docx" if ext == "docx" else "xlsx"
    if data.startswith(b"PK") and b"word/" in data[:4096]:
        return "docx"

    if b"OFXHEADER" in head.upper() or "<OFX" in text_upper or ext in ("ofx", "qfx"):
        return "ofx"
    if "CAMT.053" in text_upper or "URN:ISO:STD:ISO:20022:TECH:XSD:CAMT.053" in text_upper:
        return "camt053"
    if text_head.lstrip().startswith("<?xml") and "CAMT" in text_upper:
        return "camt053"
    if re.search(r":20[A-Z]:|:61:|:62[FM]:", text_head) or ext in ("sta", "mt940", "swi"):
        if ":20" in text_head or ":61:" in text_head:
            return "mt940"

    # CNAB 240: linhas ~240 chars, frequentemente começa com código de banco
    if _looks_like_cnab240(text_head) or ext in ("ret", "rem", "cnab", "cnab240"):
        if _looks_like_cnab240(text_head) or ext in ("ret", "rem", "cnab", "cnab240"):
            return "cnab240"

    if ext == "csv" or (ext == "txt" and ("," in text_head[:200] or ";" in text_head[:200])):
        if ext == "csv":
            return "csv"
    if ext == "csv":
        return "csv"
    if ext in ("txt", "text", "log"):
        return "txt"
    if ext == "docx":
        return "docx"
    if ext in ("jpg", "jpeg"):
        return "jpg"
    if ext == "png":
        return "png"
    if ext == "pdf":
        return "pdf"
    if ext in ("ofx", "qfx"):
        return "ofx"
    if ext in ("xml",) and "CAMT" in text_upper:
        return "camt053"

    # CSV heurística
    lines = [ln for ln in text_head.splitlines() if ln.strip()]
    if len(lines) >= 2 and (lines[0].count(";") >= 2 or lines[0].count(",") >= 2):
        return "csv"

    if ext:
        return ext
    return "unknown"


def _looks_like_cnab240(text: str) -> bool:
    lines = [ln.rstrip("\r\n") for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    sample = lines[:5]
    lengths = [len(ln) for ln in sample]
    if sum(1 for n in lengths if 235 <= n <= 245) >= 2:
        return True
    # Header de arquivo CNAB: posição 8 = '0' (tipo registro), tamanho 240
    first = sample[0]
    if len(first) >= 240 and first[7:8] == "0":
        return True
    return False
