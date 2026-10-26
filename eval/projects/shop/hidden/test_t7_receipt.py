from shop.models import Item, LineItem, Order
from shop.receipt import format_money, format_receipt


def test_format_money():
    assert format_money(12345) == "123.45"
    assert format_money(5) == "0.05"
    assert format_money(0) == "0.00"
    assert format_money(100) == "1.00"
    assert format_money(-150) == "-1.50"


def test_receipt_exact():
    items = {"A": Item("A", "Mug", 1250), "B": Item("B", "Tea", 399)}
    order = Order("o9", [LineItem("A", 2), LineItem("B", 1)], 2899, 0, 725, 3624)
    assert format_receipt(order, items) == "\n".join([
        "Order o9",
        "2 x Mug @ 12.50 = 25.00",
        "1 x Tea @ 3.99 = 3.99",
        "Subtotal: 28.99",
        "Discount: -0.00",
        "Tax: 7.25",
        "Total: 36.24",
    ])
