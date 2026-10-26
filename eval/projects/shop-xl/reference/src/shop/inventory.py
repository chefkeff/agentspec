import itertools
from typing import Dict, Tuple

from .errors import OutOfStock, UnknownSku
from .models import Item


def _check_qty(qty: int) -> None:
    if qty <= 0:
        raise ValueError("qty must be positive")


class Inventory:
    def __init__(self) -> None:
        self._items: Dict[str, Item] = {}
        self._on_hand: Dict[str, int] = {}
        self._held: Dict[str, Tuple[str, int]] = {}
        self._ids = itertools.count(1)

    def add_item(self, item: Item, qty: int) -> None:
        _check_qty(qty)
        self._items[item.sku] = item
        self._on_hand[item.sku] = self._on_hand.get(item.sku, 0) + qty

    def get_item(self, sku: str) -> Item:
        if sku not in self._items:
            raise UnknownSku(sku)
        return self._items[sku]

    def stock(self, sku: str) -> int:
        held = sum(q for s, q in self._held.values() if s == sku)
        return self._on_hand.get(sku, 0) - held

    def remove(self, sku: str, qty: int) -> None:
        _check_qty(qty)
        self.get_item(sku)
        if qty > self.stock(sku):
            raise OutOfStock(sku)
        self._on_hand[sku] -= qty

    def reserve(self, sku: str, qty: int) -> str:
        _check_qty(qty)
        self.get_item(sku)
        if qty > self.stock(sku):
            raise OutOfStock(sku)
        rid = f"r{next(self._ids)}"
        self._held[rid] = (sku, qty)
        return rid

    def release(self, reservation_id: str) -> None:
        del self._held[reservation_id]

    def commit(self, reservation_id: str) -> None:
        sku, qty = self._held.pop(reservation_id)
        self._on_hand[sku] -= qty
