from shop.receipt import format_money


def test_format_money():
    assert format_money(12345) == "123.45"
    assert format_money(5) == "0.05"
