from __future__ import annotations

from decimal import Decimal

from parsers.base import NormalizedRow
from parsers.supplier_a import parse

SAMPLE_CSV = (
    "sku,ean,description,price,stock\n"
    "A-1001,4006381333931,Widget Small,9.99,120\n"
    "A-1003,,Widget Large (no EAN),15.99,0\n"
)


def test_parse_returns_normalized_rows():
    rows = parse(SAMPLE_CSV)
    assert rows == [
        NormalizedRow(
            sku="A-1001",
            ean="4006381333931",
            description="Widget Small",
            price=Decimal("9.99"),
            stock=120,
        ),
        NormalizedRow(
            sku="A-1003",
            ean=None,
            description="Widget Large (no EAN)",
            price=Decimal("15.99"),
            stock=0,
        ),
    ]


def test_parse_empty_file_returns_no_rows():
    assert parse("sku,ean,description,price,stock\n") == []
