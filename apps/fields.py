from django.db import models


class MoneyField(models.PositiveBigIntegerField):
    """Monetary value stored in integer centavos (never float/decimal).

    Enforces integer semantics at the database boundary so no code path can
    silently persist a float amount.
    """

    description = "Monetary amount in centavos"

    def get_prep_value(self, value):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"Money amounts must be integer centavos, got {value!r}")
        return value
