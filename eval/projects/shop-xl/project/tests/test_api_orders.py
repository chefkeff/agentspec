from shop.api import Api
from shop.customers import Customers
from shop.inventory import Inventory
from shop.models import Item
from shop.orders import OrderStore


def test_place_order():
    inv = Inventory()
    inv.add_item(Item("A", "Apple", 1000), 5)
    customers = Customers()
    customers.add_customer("c1", "Ann", "ann@example.com")
    api = Api(inv, OrderStore(), customers)
    res = api.handle({"op": "place_order", "customer_id": "c1", "order_id": "o1", "region": "SE",
                      "lines": [{"sku": "A", "qty": 2}]})
    assert res == {"ok": True, "order_id": "o1", "total_cents": 2500, "tier": "bronze"}
