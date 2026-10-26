import pytest
from shop.tax import tax_cents


def test_rates():
    assert tax_cents(1000, "SE") == 250
    assert tax_cents(1000, "UK") == 200
    assert tax_cents(10000, "US-CA") == 725


def test_half_up_rounding():
    assert tax_cents(200, "US-CA") == 15   # 14.5 -> 15
    assert tax_cents(1000, "US-CA") == 73  # 72.5 -> 73
    assert tax_cents(100, "US-CA") == 7    # 7.25 -> 7
    assert tax_cents(2, "SE") == 1         # 0.5 -> 1
    assert tax_cents(0, "UK") == 0


def test_returns_int():
    assert isinstance(tax_cents(333, "US-CA"), int)


def test_unknown_and_case_sensitive():
    with pytest.raises(ValueError):
        tax_cents(100, "DE")
    with pytest.raises(ValueError):
        tax_cents(100, "se")
