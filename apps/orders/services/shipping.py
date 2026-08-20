from typing import NamedTuple


class ShippingMethod(NamedTuple):
    label: str
    price_cents: int


# Shipping methods are a fixed catalog for now, kept as a module constant.
SHIPPING_METHODS = {
    "standard": ShippingMethod("Standard Shipping", 0),
    "express": ShippingMethod("Express Shipping", 15000),  # ₱150.00
}
