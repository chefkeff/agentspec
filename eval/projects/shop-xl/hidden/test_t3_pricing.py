import pytest
from shop.pricing import apply_discount
from shop.errors import InvalidCode


def test_error_hierarchy():
    assert issubclass(InvalidCode, ValueError)


def test_no_code():
    assert apply_discount(1000, None) == 0
    assert apply_discount(1000, "") == 0


def test_save10_rounds_down():
    assert apply_discount(999, "SAVE10") == 99
    assert apply_discount(5, "SAVE10") == 0


def test_flat500_capped():
    assert apply_discount(300, "FLAT500") == 300
    assert apply_discount(5000, "FLAT500") == 500


def test_case_insensitive():
    assert apply_discount(1000, "save10") == 100
    assert apply_discount(1000, "Flat500") == 500


def test_invalid():
    with pytest.raises(InvalidCode):
        apply_discount(1000, "FREE")
