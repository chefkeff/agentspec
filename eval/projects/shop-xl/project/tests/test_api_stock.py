from shop.api import Api
from shop.inventory import Inventory


def test_stock_ops():
    api = Api(Inventory(), None, None)
    assert api.handle({"op": "add_stock", "sku": "A", "name": "Apple", "price_cents": 100, "qty": 3}) == {"ok": True}
    assert api.handle({"op": "stock", "sku": "A"}) == {"ok": True, "stock": 3}
