from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Item:
    sku: str
    name: str
    price_cents: int


@dataclass(frozen=True)
class LineItem:
    sku: str
    qty: int


@dataclass
class Order:
    id: str
    lines: List[LineItem]
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    total_cents: int
