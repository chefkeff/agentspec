"""Domain exceptions for the shop package."""


class UnknownSku(KeyError):
    pass


class OutOfStock(Exception):
    pass


class InvalidCode(ValueError):
    pass
