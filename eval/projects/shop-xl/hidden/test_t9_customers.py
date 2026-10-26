import pytest
from shop.customers import Customers
from shop.errors import UnknownCustomer, DuplicateCustomer


def test_error_hierarchy():
    assert issubclass(UnknownCustomer, KeyError)
    assert issubclass(DuplicateCustomer, ValueError)


def test_add_returns_customer():
    c = Customers()
    cust = c.add_customer("c1", "Ann", "ann@example.com")
    assert (cust.id, cust.name, cust.email, cust.spend_cents) == ("c1", "Ann", "ann@example.com", 0)
    assert c.get("c1") is cust


def test_duplicate():
    c = Customers()
    c.add_customer("c1", "Ann", "ann@example.com")
    with pytest.raises(DuplicateCustomer):
        c.add_customer("c1", "Bob", "bob@example.com")
    assert c.get("c1").name == "Ann"


@pytest.mark.parametrize("email", ["annexample.com", "@example.com", "a@@example.com", "a@b@example.com", "ann@example", "ann@"])
def test_invalid_email(email):
    with pytest.raises(ValueError):
        Customers().add_customer("c1", "Ann", email)


def test_tier_boundaries():
    c = Customers()
    c.add_customer("c1", "Ann", "ann@example.com")
    c.record_spend("c1", 9999)
    assert c.tier("c1") == "bronze"
    c.record_spend("c1", 1)
    assert c.tier("c1") == "silver"
    c.record_spend("c1", 39999)
    assert c.tier("c1") == "silver"
    c.record_spend("c1", 1)
    assert c.tier("c1") == "gold"


def test_unknown_and_bad_spend():
    c = Customers()
    c.add_customer("c1", "Ann", "ann@example.com")
    for call in (lambda: c.get("zz"), lambda: c.tier("zz"), lambda: c.record_spend("zz", 10)):
        with pytest.raises(UnknownCustomer):
            call()
    with pytest.raises(ValueError):
        c.record_spend("c1", 0)
    assert c.get("c1").spend_cents == 0
