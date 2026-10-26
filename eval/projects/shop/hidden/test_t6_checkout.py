import pytest
from shop.models import Item, LineItem
from shop.inventory import Inventory
from shop.checkout import checkout
from shop.errors import UnknownSku, OutOfStock


def make():
    inv = Inventory()
    inv.add_item(Item("A", "Apple", 1000), 5)
    inv.add_item(Item("B", "Bread", 250), 2)
    return inv


def test_totals_with_discount_and_tax():
    inv = make()
    order = checkout(inv, [LineItem("A", 2), LineItem("B", 2)], region="US-CA", order_id="o1", code="SAVE10")
    assert order.id == "o1"
    assert order.subtotal_cents == 2500
    assert order.discount_cents == 250
    assert order.tax_cents == 163  # 2250 * 7.25% = 163.125
    assert order.total_cents == 2413
    assert inv.stock("A") == 3
    assert inv.stock("B") == 0


def test_duplicates_combined_in_order():
    inv = make()
    order = checkout(inv, [LineItem("B", 1), LineItem("A", 1), LineItem("B", 1)], region="SE", order_id="o2")
    assert order.lines == [LineItem("B", 2), LineItem("A", 1)]
    assert order.subtotal_cents == 1500


def test_all_or_nothing_out_of_stock():
    inv = make()
    with pytest.raises(OutOfStock):
        checkout(inv, [LineItem("A", 1), LineItem("B", 3)], region="SE", order_id="o3")
    assert inv.stock("A") == 5
    assert inv.stock("B") == 2


def test_all_or_nothing_duplicates_exceed_stock():
    inv = make()
    with pytest.raises(OutOfStock):
        checkout(inv, [LineItem("B", 2), LineItem("A", 1), LineItem("B", 1)], region="SE", order_id="o4")
    assert inv.stock("A") == 5
    assert inv.stock("B") == 2


def test_all_or_nothing_unknown():
    inv = make()
    with pytest.raises(UnknownSku):
        checkout(inv, [LineItem("A", 1), LineItem("Z", 1)], region="SE", order_id="o5")
    assert inv.stock("A") == 5
