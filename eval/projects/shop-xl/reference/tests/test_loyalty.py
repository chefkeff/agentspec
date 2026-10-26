from shop.pricing import loyalty_discount


def test_loyalty():
    assert loyalty_discount(10000, "gold") == 500
    assert loyalty_discount(10000, "bronze") == 0
