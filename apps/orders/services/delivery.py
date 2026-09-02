"""Post-purchase digital delivery.

Everything a paid buyer needs to reach their purchase:
* ``order_files``        — the deliverables attached to an order's products
* ``can_access_order``   — settlement + membership checks used by downloads
* ``downloads_remaining_today`` / ``record_download`` — per-order daily cap
* ``order_access_token`` / ``resolve_access_token`` — signed, expiring links so
  the confirmation email works on any device even without an account.
"""

import logging

from django.conf import settings
from django.core import signing
from django.utils import timezone

from apps.catalog.models import ProductFile
from apps.orders.models import DownloadLog, Order

logger = logging.getLogger(__name__)

ACCESS_SALT = "virtus.order-access"
# Confirmation emails stay useful for a month before the link expires.
ACCESS_TOKEN_MAX_AGE = 60 * 60 * 24 * 30


def settled(order):
    """True when payment has settled and the buyer owns the goods."""
    return order.status in (Order.Status.PAID, Order.Status.FULFILLED)


def order_files(order):
    """Return active ProductFiles for every product in the order."""
    product_ids = order.items.values_list("product_id", flat=True)
    return ProductFile.objects.filter(product_id__in=product_ids, is_active=True).select_related(
        "product"
    )


def can_access_file(order, file_obj):
    """True when this file belongs to the order and access is still valid.

    Requires: settled order, file's product is in the order, and — for
    memberships — the item's access window hasn't ended.
    """
    if not settled(order):
        return False
    try:
        item = order.items.select_related("product").get(product_id=file_obj.product_id)
    except order.items.model.DoesNotExist:
        return False
    return item.has_active_access


def expired_membership_items(order):
    """Order items whose membership window has closed."""
    items = []
    for item in order.items.select_related("product"):
        if item.is_membership and not item.has_active_access:
            items.append(item)
    return items


def downloads_today(order):
    """Downloads already served for this order since midnight (local tz)."""
    start_of_day = timezone.localdate()
    return DownloadLog.objects.filter(order=order, created_at__date=start_of_day).count()


def downloads_remaining_today(order):
    """How many downloads the order may still serve today."""
    limit = settings.MAX_DOWNLOADS_PER_DAY_PER_ORDER
    if limit <= 0:
        # 0 or negative disables the cap entirely.
        return None
    return max(0, limit - downloads_today(order))


def record_download(order, file_obj, request):
    """Write one audit row per served download."""
    ip = request.META.get("REMOTE_ADDR")
    agent = (request.META.get("HTTP_USER_AGENT") or "")[:300]
    return DownloadLog.objects.create(
        order=order,
        file=file_obj,
        ip_address=ip,
        user_agent=agent,
    )


def order_access_token(order):
    """Return a tamper-proof token that unlocks the order on any device."""
    return signing.dumps(str(order.id), salt=ACCESS_SALT)


def resolve_access_token(token):
    """Return the Order for a valid token, else None (expired/tampered)."""
    try:
        order_id = signing.loads(token, salt=ACCESS_SALT, max_age=ACCESS_TOKEN_MAX_AGE)
    except (signing.BadSignature, signing.SignatureExpired):
        return None
    return Order.objects.filter(id=order_id).first()
