from shop.api import Api
from shop.inventory import Inventory


def test_add_and_query():
    api = Api(Inventory(), None, None)
    assert api.handle({"op": "add_stock", "sku": "A", "name": "Apple", "price_cents": 100, "qty": 3}) == {"ok": True}
    assert api.handle({"op": "add_stock", "sku": "A", "name": "Apple", "price_cents": 100, "qty": 2}) == {"ok": True}
    assert api.handle({"op": "stock", "sku": "A"}) == {"ok": True, "stock": 5}
    assert api.handle({"op": "stock", "sku": "Z"}) == {"ok": True, "stock": 0}


def test_errors_mapped():
    api = Api(Inventory(), None, None)
    assert api.handle({"op": "add_stock", "sku": "A", "name": "Apple", "price_cents": 100, "qty": 0}) == {"ok": False, "error": "ValueError"}
    assert api.handle({"op": "nope"}) == {"ok": False, "error": "UnknownOp"}
