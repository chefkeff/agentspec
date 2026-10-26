from shop.api import Api
from shop.customers import Customers
from shop.models import LineItem, Order
from shop.orders import OrderStore


def test_report_empty_and_filled():
    store = OrderStore()
    api = Api(None, store, Customers())
    assert api.handle({"op": "report"}) == {"ok": True, "count": 0, "revenue_cents": 0, "tax_cents": 0, "top_sku": None}
    store.save(Order("o1", [LineItem("A", 2)], 2000, 0, 500, 2500), "c1")
    store.save(Order("o2", [LineItem("B", 3)], 750, 0, 188, 938), "c2")
    assert api.handle({"op": "report"}) == {"ok": True, "count": 2, "revenue_cents": 3438, "tax_cents": 688, "top_sku": "B"}


def test_customer_op():
    customers = Customers()
    customers.add_customer("c1", "Ann", "ann@example.com")
    customers.record_spend("c1", 60000)
    api = Api(None, OrderStore(), customers)
    assert api.handle({"op": "customer", "customer_id": "c1"}) == {"ok": True, "name": "Ann", "spend_cents": 60000, "tier": "gold"}
    assert api.handle({"op": "customer", "customer_id": "zz"}) == {"ok": False, "error": "UnknownCustomer"}
