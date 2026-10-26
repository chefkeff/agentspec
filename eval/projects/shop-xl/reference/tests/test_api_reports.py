from shop.api import Api
from shop.customers import Customers
from shop.models import LineItem, Order
from shop.orders import OrderStore


def test_report_and_customer():
    store = OrderStore()
    store.save(Order("o1", [LineItem("A", 2)], 2000, 0, 500, 2500), "c1")
    customers = Customers()
    customers.add_customer("c1", "Ann", "ann@example.com")
    api = Api(None, store, customers)
    assert api.handle({"op": "report"})["revenue_cents"] == 2500
    assert api.handle({"op": "customer", "customer_id": "c1"}) == {"ok": True, "name": "Ann", "spend_cents": 0, "tier": "bronze"}
