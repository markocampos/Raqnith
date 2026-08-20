"""Pure money arithmetic in integer centavos.

All amounts are non-negative integers representing centavos (₱1.00 == 100).
No floats or Decimals are used anywhere in the money path; rounding is done
with half-up integer math at the centavo.
"""

MINIMUM_TRANSACTION_CENTS = 100  # ₱1.00


def _ensure_int(amount):
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ValueError(f"Amount must be an integer number of centavos, got {amount!r}")
    return amount


def add_centavos(*amounts):
    """Sum any number of centavo amounts."""
    total = 0
    for amount in amounts:
        total += _ensure_int(amount)
    return total


def subtract_centavos(a, b):
    """Return ``a - b``, refusing to produce a negative amount."""
    a = _ensure_int(a)
    b = _ensure_int(b)
    if b > a:
        raise ValueError("Cannot subtract to a negative amount.")
    return a - b


def percent_of(amount, pct):
    """Return ``pct`` percent of ``amount``, rounded half-up to the centavo."""
    amount = _ensure_int(amount)
    if not isinstance(pct, int) or pct < 0 or pct > 100:
        raise ValueError(f"Percent must be an integer between 0 and 100, got {pct!r}")
    return (amount * pct + 50) // 100


def apply_percent_discount(amount, pct):
    """Return ``amount`` reduced by ``pct`` percent, rounded to the centavo."""
    return subtract_centavos(amount, percent_of(amount, pct))


def validate_minimum(amount, minimum=MINIMUM_TRANSACTION_CENTS):
    """Raise ValueError if ``amount`` is below the minimum transaction value."""
    amount = _ensure_int(amount)
    if amount < minimum:
        raise ValueError(f"Amount {amount} is below the minimum of {minimum} centavos.")
    return amount
