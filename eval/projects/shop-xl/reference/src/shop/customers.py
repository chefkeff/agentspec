from typing import Dict

from .errors import DuplicateCustomer, UnknownCustomer
from .models import Customer


def _valid_email(email: str) -> bool:
    if email.count("@") != 1:
        return False
    local, domain = email.split("@")
    return bool(local) and "." in domain


class Customers:
    def __init__(self) -> None:
        self._by_id: Dict[str, Customer] = {}

    def add_customer(self, id: str, name: str, email: str) -> Customer:
        if id in self._by_id:
            raise DuplicateCustomer(id)
        if not _valid_email(email):
            raise ValueError(f"invalid email {email}")
        cust = Customer(id, name, email)
        self._by_id[id] = cust
        return cust

    def get(self, id: str) -> Customer:
        if id not in self._by_id:
            raise UnknownCustomer(id)
        return self._by_id[id]

    def record_spend(self, id: str, cents: int) -> None:
        cust = self.get(id)
        if cents <= 0:
            raise ValueError("spend must be positive")
        cust.spend_cents += cents

    def tier(self, id: str) -> str:
        spend = self.get(id).spend_cents
        if spend >= 50000:
            return "gold"
        if spend >= 10000:
            return "silver"
        return "bronze"
