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
