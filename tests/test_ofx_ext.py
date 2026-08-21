"""Testes do extrator OFX — PagBank e similares com LEDGERBAL vazio."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.to_xlsx.extractors.ofx_ext import (
    extract_ofx,
    _parse_amount,
    _parse_stmttrn,
    _sanitize_ofx_balances,
)
from app.to_xlsx.structure import structure_data
from app.to_xlsx import FIXED_COLUMNS

PAGBANK_EMPTY_LEDGER = """\
OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<DTSERVER>20260531120000
<LANGUAGE>POR
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>1
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>290
<ACCTID>12345-6
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260101
<DTEND>20260531
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260115120000[-3:BRT]
<TRNAMT>1500.00
<FITID>pix-001
<MEMO>Pix recebido Fulano
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260120
<TRNAMT>-35,50
<FITID>deb-002
<NAME>Padaria Central
<MEMO>Compra debito
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>
<DTASOF>
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


class SanitizeBalancesTest(unittest.TestCase):
    def test_fills_empty_balamt_and_dtasof(self):
        out = _sanitize_ofx_balances(PAGBANK_EMPTY_LEDGER)
        self.assertIn("<BALAMT>0.00", out)
        self.assertIn("<DTASOF>19700101", out)


class ParseStmttrnTest(unittest.TestCase):
    def test_pagbank_empty_ledger_extracts_transactions(self):
        records = _parse_stmttrn(PAGBANK_EMPTY_LEDGER)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["data"], "15/01/2026")
        self.assertEqual(records[0]["valor"], 1500.0)
        self.assertEqual(records[0]["tipo"], "credito")
        self.assertEqual(records[0]["documento"], "pix-001")
        self.assertEqual(records[1]["valor"], -35.5)
        self.assertEqual(records[1]["tipo"], "debito")
        self.assertIn("Padaria Central", records[1]["descricao"])

    def test_brazilian_thousands_amount(self):
        self.assertEqual(_parse_amount("1.234,56"), 1234.56)
        self.assertEqual(_parse_amount("-10.50"), -10.5)
        self.assertEqual(_parse_amount(""), 0.0)


class ExtractOfxFileTest(unittest.TestCase):
    def test_extract_ofx_does_not_raise_on_empty_ledger(self):
        with tempfile.NamedTemporaryFile(suffix=".ofx", delete=False) as tmp:
            tmp.write(PAGBANK_EMPTY_LEDGER.encode("cp1252"))
            path = tmp.name
        try:
            result = extract_ofx(path)
        finally:
            Path(path).unlink(missing_ok=True)

        self.assertTrue(result.structured)
        self.assertEqual(result.source_format, "ofx")
        self.assertEqual(len(result.records), 2)

    def test_structured_empty_does_not_require_openai(self):
        from app.to_xlsx.extractors import ExtractionResult

        cols, rows = structure_data(
            ExtractionResult(source_format="ofx", records=[], structured=True),
            schema_mode="fixed",
            columns=list(FIXED_COLUMNS),
            openai_api_key="",
            openai_model="gpt-4o-mini",
            openai_timeout=10,
            openai_max_chars=1000,
        )
        self.assertEqual(cols, list(FIXED_COLUMNS))
        self.assertEqual(rows, [])

    def test_pipeline_xlsx_from_pagbank_ofx(self):
        try:
            from app.to_xlsx.pipeline import ToXlsxPipeline
        except ImportError as exc:
            self.skipTest(f"dependências do pipeline ausentes: {exc}")
        pipeline = ToXlsxPipeline()
        result = pipeline.run(
            PAGBANK_EMPTY_LEDGER.encode("cp1252"),
            filename="pagbank_012026_a_052026.ofx",
        )
        self.assertEqual(result.source_format, "ofx")
        self.assertEqual(result.rows, 2)
        self.assertGreater(len(result.xlsx_bytes), 0)


if __name__ == "__main__":
    unittest.main()
