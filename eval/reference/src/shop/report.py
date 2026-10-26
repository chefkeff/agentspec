from typing import Dict, List

from .models import Order


def summarize(orders: List[Order]) -> dict:
    qty: Dict[str, int] = {}
    for order in orders:
        for line in order.lines:
            qty[line.sku] = qty.get(line.sku, 0) + line.qty
    top = min(qty, key=lambda s: (-qty[s], s)) if qty else None
    return {
        "count": len(orders),
        "revenue_cents": sum(o.total_cents for o in orders),
        "tax_cents": sum(o.tax_cents for o in orders),
        "top_sku": top,
    }
