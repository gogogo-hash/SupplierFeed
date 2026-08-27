from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class NormalizedRow:
    sku: str
    ean: str | None
    description: str
    price: Decimal
    stock: int


class Parser(Protocol):
    def __call__(self, raw_content: str) -> list[NormalizedRow]: ...
