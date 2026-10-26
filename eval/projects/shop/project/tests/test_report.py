from shop.models import LineItem, Order
from shop.report import summarize


def test_summary():
    orders = [Order("o1", [LineItem("A", 2)], 2000, 0, 500, 2500)]
    s = summarize(orders)
    assert s["count"] == 1
    assert s["revenue_cents"] == 2500
    assert s["top_sku"] == "A"
