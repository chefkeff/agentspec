import pytest
from shop.models import Item
from shop.inventory import Inventory
from shop.errors import OutOfStock


def test_add_and_remove():
    inv = Inventory()
    inv.add_item(Item("A", "Apple", 100), 5)
    inv.remove("A", 2)
    assert inv.stock("A") == 3
    assert inv.get_item("A").name == "Apple"


def test_out_of_stock():
    inv = Inventory()
    inv.add_item(Item("A", "Apple", 100), 1)
    with pytest.raises(OutOfStock):
        inv.remove("A", 2)
