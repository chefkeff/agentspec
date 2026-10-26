import pytest
from shop.models import Item
from shop.inventory import Inventory
from shop.errors import UnknownSku, OutOfStock


def make():
    inv = Inventory()
    inv.add_item(Item("A", "Apple", 100), 5)
    return inv


def test_error_hierarchy():
    assert issubclass(UnknownSku, KeyError)
    assert issubclass(OutOfStock, Exception)


def test_add_accumulates_and_keeps_latest_item():
    inv = make()
    inv.add_item(Item("A", "Green Apple", 120), 3)
    assert inv.stock("A") == 8
    assert inv.get_item("A") == Item("A", "Green Apple", 120)


def test_unknown_sku():
    inv = make()
    assert inv.stock("Z") == 0
    with pytest.raises(UnknownSku):
        inv.get_item("Z")
    with pytest.raises(UnknownSku):
        inv.remove("Z", 1)


def test_remove_exact_and_too_many():
    inv = make()
    with pytest.raises(OutOfStock):
        inv.remove("A", 6)
    assert inv.stock("A") == 5
    inv.remove("A", 5)
    assert inv.stock("A") == 0


@pytest.mark.parametrize("qty", [0, -1])
def test_non_positive_qty(qty):
    inv = make()
    with pytest.raises(ValueError):
        inv.add_item(Item("B", "Banana", 50), qty)
    with pytest.raises(ValueError):
        inv.remove("A", qty)
    assert inv.stock("A") == 5
