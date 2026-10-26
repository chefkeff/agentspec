from shop.models import LineItem, Order
from shop.report import summarize


def test_empty():
    assert summarize([]) == {"count": 0, "revenue_cents": 0, "tax_cents": 0, "top_sku": None}


def test_aggregates_and_top_sku_across_orders():
    orders = [
        Order("o1", [LineItem("B", 2), LineItem("A", 1)], 0, 0, 100, 1000),
        Order("o2", [LineItem("A", 2)], 0, 0, 50, 500),
        Order("o3", [LineItem("C", 3)], 0, 0, 25, 250),
    ]
    assert summarize(orders) == {"count": 3, "revenue_cents": 1750, "tax_cents": 175, "top_sku": "A"}


def test_tie_broken_alphabetically():
    orders = [Order("o1", [LineItem("B", 2), LineItem("A", 2)], 0, 0, 0, 0)]
    assert summarize(orders)["top_sku"] == "A"
