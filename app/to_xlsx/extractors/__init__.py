"""Resultado padronizado da extração."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractionResult:
    source_format: str
    records: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    structured: bool = False
