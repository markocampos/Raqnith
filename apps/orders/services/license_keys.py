"""Auto-issued license / access codes for software products.

Sellers flag a product with ``requires_license_key`` in the admin; every
settled order item then gets exactly one unique, human-readable code
(e.g. ``RAQ-K7F2-M9XQ-PT4B``). Idempotent: settling twice never duplicates.
"""

import secrets

from apps.orders.models import LicenseKey

# Crockford-style alphabet: no I, L, O, U or 0/1 (never ambiguous over the phone).
KEY_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
GROUP_SIZE = 4
GROUP_COUNT = 3


def generate_license_key(prefix="RAQ"):
    """Return a fresh key like RAQ-K7F2-M9XQ-PT4B."""
    groups = [
        "".join(secrets.choice(KEY_ALPHABET) for _ in range(GROUP_SIZE))
        for _ in range(GROUP_COUNT)
    ]
    return f"{prefix}-" + "-".join(groups)


def issue_license_keys(order):
    """Create missing license keys for an order's eligible items (idempotent).

    Called from every settlement path via ``mark_order_paid``. Items whose
    product does not require a key are skipped; items that already have one
    keep their original key.
    """
    issued = []
    for item in order.items.select_related("product"):
        if not item.requires_license_key:
            continue
        if LicenseKey.objects.filter(order_item=item).exists():
            continue
        # Collision chance is negligible but retry defensively.
        for _attempt in range(5):
            key = generate_license_key()
            try:
                license_key = LicenseKey.objects.create(order_item=item, key=key)
            except Exception:
                continue
            issued.append(license_key)
            break
        else:
            raise RuntimeError(f"Could not generate a unique license key for {item}.")
    return issued


def active_keys_for_order(order):
    """All active license keys in an order, with their product attached."""
    return LicenseKey.objects.filter(
        order_item__order=order, revoked_at__isnull=True
    ).select_related("order_item__product")
