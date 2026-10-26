import pytest
from shop.models import LineItem, Order
from shop.orders import OrderStore
from shop.errors import UnknownOrder, DuplicateOrder


def order(oid):
    return Order(oid, [LineItem("A", 1)], 100, 0, 25, 125)


def test_error_hierarchy():
    assert issubclass(UnknownOrder, KeyError)
    assert issubclass(DuplicateOrder, ValueError)


def test_save_order_and_listing():
    s = OrderStore()
    o1, o2, o3 = order("o1"), order("o2"), order("o3")
    s.save(o1, "c1")
    s.save(o2, "c2")
    s.save(o3, "c1")
    assert s.all() == [o1, o2, o3]
    assert s.by_customer("c1") == [o1, o3]
    assert s.by_customer("nobody") == []


def test_duplicate_changes_nothing():
    s = OrderStore()
    o1 = order("o1")
    s.save(o1, "c1")
    with pytest.raises(DuplicateOrder):
        s.save(order("o1"), "c2")
    assert s.get("o1") is o1
    assert s.by_customer("c2") == []
    assert len(s.all()) == 1


def test_unknown():
    with pytest.raises(UnknownOrder):
        OrderStore().get("nope")
