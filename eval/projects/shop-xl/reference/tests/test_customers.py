from shop.customers import Customers


def test_tiers():
    c = Customers()
    c.add_customer("c1", "Ann", "ann@example.com")
    assert c.tier("c1") == "bronze"
    c.record_spend("c1", 20000)
    assert c.tier("c1") == "silver"
    assert c.get("c1").spend_cents == 20000
