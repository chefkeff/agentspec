"""Domain exceptions for the shop package."""


class UnknownSku(KeyError):
    pass


class OutOfStock(Exception):
    pass


class InvalidCode(ValueError):
    pass


class UnknownCustomer(KeyError):
    pass


class DuplicateCustomer(ValueError):
    pass


class UnknownOrder(KeyError):
    pass


class DuplicateOrder(ValueError):
    pass
