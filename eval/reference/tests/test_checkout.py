from shop.models import Item, LineItem
from shop.inventory import Inventory
from shop.checkout import checkout


def test_basic_checkout():
    inv = Inventory()
    inv.add_item(Item("A", "Apple", 1000), 3)
    order = checkout(inv, [LineItem("A", 2)], region="SE", order_id="o1")
    assert order.subtotal_cents == 2000
    assert order.tax_cents == 500
    assert order.total_cents == 2500
    assert inv.stock("A") == 1
