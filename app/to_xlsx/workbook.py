"""Geração de bytes .xlsx via openpyxl."""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook


def build_xlsx_bytes(columns: list[str], rows: list[dict[str, Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "dados"

    ws.append(columns)
    for row in rows:
        ws.append([row.get(c, "") for c in columns])

    # Largura básica
    for idx, col in enumerate(columns, start=1):
        ws.column_dimensions[ws.cell(1, idx).column_letter].width = max(12, min(40, len(col) + 4))

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
