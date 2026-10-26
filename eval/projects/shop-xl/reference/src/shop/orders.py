from typing import Dict, List, Tuple

from .errors import DuplicateOrder, UnknownOrder
from .models import Order


class OrderStore:
    def __init__(self) -> None:
        self._orders: Dict[str, Tuple[Order, str]] = {}

    def save(self, order: Order, customer_id: str) -> None:
        if order.id in self._orders:
            raise DuplicateOrder(order.id)
        self._orders[order.id] = (order, customer_id)

    def get(self, order_id: str) -> Order:
        if order_id not in self._orders:
            raise UnknownOrder(order_id)
        return self._orders[order_id][0]

    def all(self) -> List[Order]:
        return [o for o, _ in self._orders.values()]

    def by_customer(self, customer_id: str) -> List[Order]:
        return [o for o, c in self._orders.values() if c == customer_id]
