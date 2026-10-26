from typing import Dict

from .models import Item, Order


def format_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def format_receipt(order: Order, items: Dict[str, Item]) -> str:
    out = [f"Order {order.id}"]
    for line in order.lines:
        item = items[line.sku]
        out.append(f"{line.qty} x {item.name} @ {format_money(item.price_cents)} = {format_money(item.price_cents * line.qty)}")
    out += [
        f"Subtotal: {format_money(order.subtotal_cents)}",
        f"Discount: -{format_money(order.discount_cents)}",
        f"Tax: {format_money(order.tax_cents)}",
        f"Total: {format_money(order.total_cents)}",
    ]
    return "\n".join(out)
