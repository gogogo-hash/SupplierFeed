from __future__ import annotations

from . import supplier_a
from .base import Parser

PARSERS: dict[str, Parser] = {
    "supplier_a": supplier_a.parse,
}


class UnknownSupplierError(KeyError):
    """Raised when no parser is registered for a supplier_code."""


def get_parser(supplier_code: str) -> Parser:
    try:
        return PARSERS[supplier_code]
    except KeyError:
        raise UnknownSupplierError(supplier_code) from None
