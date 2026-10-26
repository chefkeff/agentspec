from typing import Dict, List, Optional

from .inventory import Inventory
from .models import LineItem, Order
from .pricing import apply_discount
from .tax import tax_cents


def checkout(inventory: Inventory, cart: List[LineItem], region: str, order_id: str, code: Optional[str] = None) -> Order:
    combined: Dict[str, int] = {}
    for line in cart:
        combined[line.sku] = combined.get(line.sku, 0) + line.qty
    lines = [LineItem(sku, qty) for sku, qty in combined.items()]

    held = []
    try:
        for line in lines:
            held.append(inventory.reserve(line.sku, line.qty))
        subtotal = sum(inventory.get_item(l.sku).price_cents * l.qty for l in lines)
        discount = apply_discount(subtotal, code)
        tax = tax_cents(subtotal - discount, region)
    except Exception:
        for rid in held:
            inventory.release(rid)
        raise

    for rid in held:
        inventory.commit(rid)
    return Order(order_id, lines, subtotal, discount, tax, subtotal - discount + tax)
