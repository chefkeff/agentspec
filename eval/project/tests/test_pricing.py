from shop.pricing import apply_discount


def test_codes():
    assert apply_discount(1000, None) == 0
    assert apply_discount(1000, "SAVE10") == 100
    assert apply_discount(1000, "FLAT500") == 500
