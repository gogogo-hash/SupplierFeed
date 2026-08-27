from __future__ import annotations

import csv
import io
from decimal import Decimal

from .base import NormalizedRow


def parse(raw_content: str) -> list[NormalizedRow]:
    reader = csv.DictReader(io.StringIO(raw_content))
    return [
        NormalizedRow(
            sku=record["sku"].strip(),
            ean=record["ean"].strip() or None,
            description=record["description"].strip(),
            price=Decimal(record["price"]),
            stock=int(record["stock"]),
        )
        for record in reader
    ]
