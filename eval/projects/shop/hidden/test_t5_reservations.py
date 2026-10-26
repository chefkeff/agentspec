import pytest
from shop.models import Item
from shop.inventory import Inventory
from shop.errors import UnknownSku, OutOfStock


def make():
    inv = Inventory()
    inv.add_item(Item("A", "Apple", 100), 5)
    return inv


def test_reserved_units_are_held():
    inv = make()
    inv.reserve("A", 3)
    assert inv.stock("A") == 2
    with pytest.raises(OutOfStock):
        inv.remove("A", 3)
    with pytest.raises(OutOfStock):
        inv.reserve("A", 3)


def test_unique_ids():
    inv = make()
    assert inv.reserve("A", 1) != inv.reserve("A", 1)


def test_release_and_commit():
    inv = make()
    r1 = inv.reserve("A", 2)
    r2 = inv.reserve("A", 2)
    inv.release(r1)
    assert inv.stock("A") == 3
    inv.commit(r2)
    assert inv.stock("A") == 3
    inv.add_item(Item("A", "Apple", 100), 1)
    assert inv.stock("A") == 4


def test_finished_or_unknown_ids():
    inv = make()
    rid = inv.reserve("A", 1)
    inv.commit(rid)
    with pytest.raises(KeyError):
        inv.commit(rid)
    with pytest.raises(KeyError):
        inv.release(rid)
    with pytest.raises(KeyError):
        inv.release("nope")


def test_reserve_errors():
    inv = make()
    with pytest.raises(UnknownSku):
        inv.reserve("Z", 1)
    with pytest.raises(ValueError):
        inv.reserve("A", 0)
    assert inv.stock("A") == 5
