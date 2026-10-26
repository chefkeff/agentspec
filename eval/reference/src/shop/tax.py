RATES_BP = {"SE": 2500, "UK": 2000, "US-CA": 725}


def tax_cents(amount_cents: int, region: str) -> int:
    if region not in RATES_BP:
        raise ValueError(f"unknown region {region}")
    return (amount_cents * RATES_BP[region] + 5000) // 10000
