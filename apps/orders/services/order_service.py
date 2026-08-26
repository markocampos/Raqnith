import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.cart.models import Cart, CartItem
from apps.catalog.services.pricing import (
    MINIMUM_TRANSACTION_CENTS,
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

logger = logging.getLogger(__name__)


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


def is_free_order(order):
    """True when the order total is below the minimum transaction amount.

    Such orders are settled as free checkout: no PayMongo intent is created
    and no money moves, but confirmation, fulfillment, and receipts all run
    through the normal paid path.
    """
    return order.total_amount < MINIMUM_TRANSACTION_CENTS


def settle_free_order(order):
    """Settle a zero-total order through the standard paid workflow.

    Used by checkout when every item in the cart is free (total < ₱1): the
    buyer still confirms email + terms, then the order transitions
    PENDING_PAYMENT → PAID and reuses ``mark_order_paid`` so license keys,
    membership access, the confirmation email, and cart clearing all behave
    exactly like an ordinary paid order. Idempotent.
    """
    if order.status == Order.Status.DRAFT:
        order.transition_to(Order.Status.PENDING_PAYMENT)

    logger.info("free checkout settlement order=%s total=%s", order.id, order.total_amount)
    return mark_order_paid(order)


def clear_purchased_cart_items(order):
    """Remove the order's products from the buyer's cart after payment.

    Called from ``mark_order_paid`` so every settlement path (webhook, return
    view, retry reconciliation, status view) clears the cart exactly once.
    Only the purchased products are removed — items the buyer added while the
    payment was pending stay in the cart.
    """
    product_ids = [item.product_id for item in order.items.all()]
    if not product_ids:
        return

    if order.user_id:
        carts = Cart.objects.filter(user_id=order.user_id)
    elif order.session_key:
        carts = Cart.objects.filter(session_key=order.session_key)
    else:
        return

    CartItem.objects.filter(cart__in=carts, product_id__in=product_ids).delete()


def mark_order_paid(order):
    """Settle an order as PAID, setting ``paid_at`` (total-safe + idempotent).

    Used by the payment webhook, polling reconciliation, and the return view.
    Money arriving is authoritative: this function must never raise for state
    reasons, or the webhook retries forever and the buyer's browser silently
    misses the confirmation.

    * PAID / FULFILLED → already settled, no-op.
    * PENDING_PAYMENT  → normal happy-path transition.
    * Anything else (CANCELLED / PAYMENT_FAILED / DRAFT) means local state
      drifted while money was actually captured (e.g. a later checkout
      cancelled a pending order whose QR was still scanned). Force-settle to
      protect the buyer and log loudly for manual follow-up.
    """
    if order.status in (Order.Status.PAID, Order.Status.FULFILLED):
        clear_purchased_cart_items(order)
        return order

    if order.status != Order.Status.PENDING_PAYMENT:
        logger.error(
            "order %s paid at PayMongo but locally %s — force-settling to PAID.",
            order.id,
            order.status,
        )
        order.status = Order.Status.PAID
        if order.paid_at is None:
            order.paid_at = timezone.now()
        order.save(update_fields=["status", "paid_at", "updated_at"])
    else:
        order = order.transition_to(Order.Status.PAID)

    clear_purchased_cart_items(order)
    fulfill_order_items(order)
    _queue_confirmation_email(order)
    return order


def fulfill_order_items(order):
    """Per-item fulfillment side effects after payment settles.

    * Memberships get ``access_until`` = paid_at + configured duration.
    * Products flagged ``requires_license_key`` each receive one code.
    Both steps are idempotent so replays never duplicate anything.
    """
    from apps.orders.services.license_keys import issue_license_keys

    memberships_changed = []
    for item in order.items.select_related("product"):
        if (
            item.is_membership
            and item.access_until is None
            and item.product.membership_duration_days
        ):
            item.access_until = (order.paid_at or timezone.now()) + timezone.timedelta(
                days=item.product.membership_duration_days
            )
            item.save(update_fields=["access_until"])
            memberships_changed.append(item)

    if memberships_changed:
        logger.info(
            "membership access set order=%s items=%s",
            order.id,
            [str(i.id) for i in memberships_changed],
        )

    issued = issue_license_keys(order)
    if issued:
        logger.info(
            "license keys issued order=%s count=%s", order.id, len(issued)
        )


def _queue_confirmation_email(order):
    """Send the receipt email after the settling transaction commits."""
    from apps.orders.services.email_service import send_order_confirmation

    transaction.on_commit(lambda: send_order_confirmation(order))
