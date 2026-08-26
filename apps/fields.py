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


class HTTPSURLField(models.URLField):
    """URLField whose forms assume ``https://`` for scheme-less input.

    Django 5.x deprecates the legacy http:// default (and its transitional
    FORMS_URLFIELD_ASSUME_HTTPS setting); this adopts the Django 6.0 default
    per-field without any deprecation noise.
    """

    def formfield(self, **kwargs):
        return super().formfield(**{"assume_scheme": "https", **kwargs})
