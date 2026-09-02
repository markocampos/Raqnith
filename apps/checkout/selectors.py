from apps.coupons.models import Coupon
from apps.orders.constants import CURRENCY
from apps.orders.exceptions import OrderBuildError
from apps.orders.services.order_service import compute_totals, unique_products


def build_checkout_context(cart, coupon_code=None, shipping_method="standard"):
    """Build the template context for the checkout page.

    Totals are computed server-side from database prices only; the browser
    never supplies or re-derives an amount.
    """
    items = list(cart.items.select_related("product"))
    if not items:
        raise OrderBuildError({"cart": "The cart is empty."})

    coupon = None
    if coupon_code:
        coupon = Coupon.objects.filter(code__iexact=coupon_code, active=True).first()
        if coupon is not None and coupon.is_expired:
            coupon = None

    products = unique_products(items)
    subtotal, discount, shipping, tax, total = compute_totals(products, coupon, shipping_method)

    return {
        "cart_id": str(cart.id),
        "currency": CURRENCY,
        "shipping_method": shipping_method,
        "coupon_code": coupon_code,
        "line_items": [
            {
                "product": product,
                "unit_price_cents": product.price_cents,
                "line_total_cents": product.price_cents,
            }
            for product in products
        ],
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "shipping_cents": shipping,
        "tax_cents": tax,
        "total_cents": total,
    }
