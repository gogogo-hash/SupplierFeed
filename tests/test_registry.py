from __future__ import annotations

import pytest

from parsers.registry import UnknownSupplierError, get_parser
from parsers.supplier_a import parse as supplier_a_parse


def test_get_parser_returns_registered_parser():
    assert get_parser("supplier_a") is supplier_a_parse


def test_get_parser_raises_for_unknown_supplier():
    with pytest.raises(UnknownSupplierError):
        get_parser("supplier_zzz")
