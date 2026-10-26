import pytest
from shop.pricing import loyalty_discount


def test_rates_round_down():
    assert loyalty_discount(10000, "gold") == 500
    assert loyalty_discount(10000, "silver") == 200
    assert loyalty_discount(10000, "bronze") == 0
    assert loyalty_discount(999, "gold") == 49
    assert loyalty_discount(149, "silver") == 2


def test_unknown_tier():
    with pytest.raises(ValueError):
        loyalty_discount(1000, "platinum")
    with pytest.raises(ValueError):
        loyalty_discount(1000, "Gold")
