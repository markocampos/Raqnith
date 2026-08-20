from django.core.exceptions import ValidationError

from apps.catalog.services.pricing import validate_minimum
from apps.orders.constants import CURRENCY
from apps.orders.services.shipping import SHIPPING_METHODS


def validate_product(product):
    if not product.is_available:
        raise ValidationError("This product is not available.", code="unavailable")
    return product


def validate_coupon(coupon):
    if coupon is None:
        raise ValidationError("Invalid coupon code.", code="invalid")
    if not coupon.active:
        raise ValidationError("This coupon is inactive.", code="inactive")
    if coupon.is_expired:
        raise ValidationError("This coupon has expired.", code="expired")
    return coupon


def validate_shipping_option(method_id):
    if method_id not in SHIPPING_METHODS:
        raise ValidationError(f"Unknown shipping method: {method_id!r}.", code="invalid_shipping")
    return method_id


def validate_currency(currency):
    if currency != CURRENCY:
        raise ValidationError(f"Unsupported currency: {currency!r}.", code="unsupported_currency")
    return currency


def validate_minimum_transaction(total_cents):
    try:
        validate_minimum(total_cents)
    except ValueError as exc:
        raise ValidationError(str(exc), code="below_minimum") from exc
    return total_cents
