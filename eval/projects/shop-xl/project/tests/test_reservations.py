from shop.models import Item
from shop.inventory import Inventory


def test_reserve_and_release():
    inv = Inventory()
    inv.add_item(Item("A", "Apple", 100), 5)
    rid = inv.reserve("A", 2)
    assert inv.stock("A") == 3
    inv.release(rid)
    assert inv.stock("A") == 5
