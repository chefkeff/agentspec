from shop.models import LineItem, Order
from shop.orders import OrderStore


def test_save_and_get():
    s = OrderStore()
    o = Order("o1", [LineItem("A", 1)], 100, 0, 25, 125)
    s.save(o, "c1")
    assert s.get("o1") is o
    assert s.by_customer("c1") == [o]
