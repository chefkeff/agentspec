"""A tiny request/response API over the shop domain.

Register operations with @handler("op_name"). A handler takes (api, req)
and returns a dict of result fields; Api.handle wraps it.
"""
from typing import Callable, Dict

HANDLERS: Dict[str, Callable] = {}


def handler(op: str):
    def register(fn: Callable) -> Callable:
        HANDLERS[op] = fn
        return fn
    return register


class Api:
    def __init__(self, inventory, store, customers):
        self.inventory = inventory
        self.store = store
        self.customers = customers

    def handle(self, req: dict) -> dict:
        fn = HANDLERS.get(req.get("op"))
        if fn is None:
            return {"ok": False, "error": "UnknownOp"}
        try:
            return {"ok": True, **fn(self, req)}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__}


@handler("add_stock")
def _add_stock(api, req):
    from .models import Item
    api.inventory.add_item(Item(req["sku"], req["name"], req["price_cents"]), req["qty"])
    return {}


@handler("stock")
def _stock(api, req):
    return {"stock": api.inventory.stock(req["sku"])}


@handler("place_order")
def _place_order(api, req):
    from .checkout import checkout
    from .errors import DuplicateOrder
    from .errors import UnknownOrder
    from .models import LineItem
    customer_id = req["customer_id"]
    api.customers.get(customer_id)
    try:
        api.store.get(req["order_id"])
        raise DuplicateOrder(req["order_id"])
    except UnknownOrder:
        pass
    lines = [LineItem(l["sku"], l["qty"]) for l in req["lines"]]
    order = checkout(api.inventory, lines, region=req["region"], order_id=req["order_id"], code=req.get("code"))
    api.store.save(order, customer_id)
    api.customers.record_spend(customer_id, order.total_cents)
    return {"order_id": order.id, "total_cents": order.total_cents, "tier": api.customers.tier(customer_id)}


@handler("report")
def _report(api, req):
    from .report import summarize
    return summarize(api.store.all())


@handler("customer")
def _customer(api, req):
    cust = api.customers.get(req["customer_id"])
    return {"name": cust.name, "spend_cents": cust.spend_cents, "tier": api.customers.tier(cust.id)}
