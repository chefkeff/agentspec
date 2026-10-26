from shop.tax import tax_cents


def test_rates():
    assert tax_cents(1000, "SE") == 250
    assert tax_cents(1000, "UK") == 200
