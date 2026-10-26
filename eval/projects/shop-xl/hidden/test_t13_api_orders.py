from shop.api import Api
from shop.customers import Customers
from shop.inventory import Inventory
from shop.models import Item
from shop.orders import OrderStore


def make():
    inv = Inventory()
    inv.add_item(Item("A", "Apple", 1000), 50)
    inv.add_item(Item("B", "Bread", 250), 2)
    customers = Customers()
    customers.add_customer("c1", "Ann", "ann@example.com")
    store = OrderStore()
    return Api(inv, store, customers), inv, store, customers


def place(api, oid, lines, customer="c1", code=None):
    req = {"op": "place_order", "customer_id": customer, "order_id": oid, "region": "SE", "lines": lines}
    if code:
        req["code"] = code
    return api.handle(req)


def test_happy_path_records_everything():
    api, inv, store, customers = make()
    res = place(api, "o1", [{"sku": "A", "qty": 2}, {"sku": "B", "qty": 1}], code="SAVE10")
    # subtotal 2250, discount 225, tax 25% of 2025 = 506.25 -> 506, total 2531
    assert res == {"ok": True, "order_id": "o1", "total_cents": 2531, "tier": "bronze"}
    assert store.get("o1").total_cents == 2531
    assert store.by_customer("c1")[0].id == "o1"
    assert customers.get("c1").spend_cents == 2531
    assert inv.stock("A") == 48


def test_tier_after_spend():
    api, *_ = make()
    res = place(api, "o1", [{"sku": "A", "qty": 8}])  # 8000 + 2000 tax = 10000
    assert res["tier"] == "silver"


def test_unknown_customer_changes_nothing():
    api, inv, store, _ = make()
    assert place(api, "o1", [{"sku": "A", "qty": 1}], customer="zz") == {"ok": False, "error": "UnknownCustomer"}
    assert inv.stock("A") == 50
    assert store.all() == []


def test_duplicate_order_changes_nothing():
    api, inv, store, customers = make()
    place(api, "o1", [{"sku": "A", "qty": 1}])
    assert place(api, "o1", [{"sku": "A", "qty": 1}]) == {"ok": False, "error": "DuplicateOrder"}
    assert inv.stock("A") == 49
    assert len(store.all()) == 1
    assert customers.get("c1").spend_cents == 1250


def test_out_of_stock_changes_nothing():
    api, inv, store, customers = make()
    assert place(api, "o1", [{"sku": "A", "qty": 1}, {"sku": "B", "qty": 3}]) == {"ok": False, "error": "OutOfStock"}
    assert inv.stock("A") == 50
    assert store.all() == []
    assert customers.get("c1").spend_cents == 0


def test_invalid_code():
    api, inv, *_ = make()
    assert place(api, "o1", [{"sku": "A", "qty": 1}], code="FREE") == {"ok": False, "error": "InvalidCode"}
    assert inv.stock("A") == 50
