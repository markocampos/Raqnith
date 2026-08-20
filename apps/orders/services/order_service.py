from django.core.exceptions import ValidationError
from django.db import transaction

from apps.catalog.services.pricing import (
    add_centavos,
    apply_percent_discount,
    percent_of,
    subtract_centavos,
)
from apps.coupons.models import Coupon
from apps.orders.constants import CURRENCY, TAX_RATE_PERCENT
from apps.orders.exceptions import OrderBuildError
from apps.orders.models import Order, OrderItem
from apps.orders.services.shipping import SHIPPING_METHODS
from apps.orders.validators import (
    validate_coupon,
    validate_currency,
    validate_minimum_transaction,
    validate_product,
    validate_shipping_option,
)


def unique_products(items):
    """Return the unique products from an iterable of objects exposing ``.product``.

    Digital products have no quantity, so a cart/order holds one row per
    product. The result preserves first-seen order.
    """
    products = {}
    for item in items:
        products[item.product.id] = item.product
    return [products[pid] for pid in products]


def compute_totals(line_items, coupon, shipping_method):
    """Compute ``(subtotal, discount, shipping, tax, total)`` in centavos.

    ``line_items`` is a list of Product objects, ``coupon`` is a Coupon (or
    None), and ``shipping_method`` is a validated shipping id. Amounts are
    derived purely from database prices; the caller supplies no money values.
    """
    subtotal = add_centavos(*(product.price_cents for product in line_items))
    discount = 0
    if coupon is not None:
        discounted_subtotal = apply_percent_discount(subtotal, coupon.discount_percent)
        discount = subtract_centavos(subtotal, discounted_subtotal)

    shipping = SHIPPING_METHODS[shipping_method].price_cents
    taxable = subtotal - discount + shipping
    tax = percent_of(taxable, TAX_RATE_PERCENT)
    total = add_centavos(taxable, tax)

    return subtotal, discount, shipping, tax, total


def build_order_from_cart(cart, *, coupon_code=None, shipping_method=None, user_or_session=None):
    """Build a persisted Order from a Cart, computing the authoritative total.

    Only identifiers come in: the cart's products plus a coupon code and
    shipping method id. Prices are read from the database; discount, shipping,
    and tax are recomputed server-side. Raises OrderBuildError (with an
    ``errors`` payload) and creates nothing if any input is invalid.
    """
    errors = {}

    items = list(cart.items.select_related("product"))
    if not items:
        errors["cart"] = "The cart is empty."

    if shipping_method is None:
        errors["shipping_method"] = "A shipping method is required."
    else:
        try:
            validate_shipping_option(shipping_method)
        except ValidationError as exc:
            errors["shipping_method"] = exc.messages[0]

    coupon = None
    if coupon_code:
        coupon = Coupon.objects.filter(code__iexact=coupon_code).first()
        try:
            coupon = validate_coupon(coupon)
        except ValidationError as exc:
            errors["coupon"] = exc.messages[0]

    products = unique_products(items)
    for product in products:
        try:
            validate_product(product)
        except ValidationError as exc:
            errors[f"product_{product.id}"] = exc.messages[0]

    if errors:
        raise OrderBuildError(errors)

    subtotal, discount, shipping_cents, tax, total = compute_totals(
        products, coupon, shipping_method
    )

    try:
        validate_currency(CURRENCY)
    except ValidationError as exc:
        errors["currency"] = exc.messages[0]
    try:
        validate_minimum_transaction(total)
    except ValidationError as exc:
        errors["total"] = exc.messages[0]

    if errors:
        raise OrderBuildError(errors)

    with transaction.atomic():
        order = Order(
            subtotal_amount=subtotal,
            discount_amount=discount,
            total_amount=total,
            currency=CURRENCY,
        )
        if user_or_session is None:
            order.user = cart.user
            order.session_key = cart.session_key
        elif isinstance(user_or_session, str):
            order.session_key = user_or_session
        else:
            order.user = user_or_session
        order.save()

        OrderItem.objects.bulk_create(
            [
                OrderItem(
                    order=order,
                    product=product,
                    product_name=product.name,
                    unit_price_cents=product.price_cents,
                )
                for product in products
            ]
        )

    return order


def mark_order_paid(order):
    """Transition an order to PAID, setting ``paid_at`` (idempotent).

    Used by the payment webhook inside its atomic transaction. A no-op when the
    order is already paid so replays and the return-view reconciliation path
    remain safe. Expects the order to be in PENDING_PAYMENT (the state set by
    the checkout before the PayMongo intent is created).
    """
    if order.status == Order.Status.PAID:
        return order
    return order.transition_to(Order.Status.PAID)
