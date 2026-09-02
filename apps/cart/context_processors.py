from django.conf import settings
from apps.cart.services import get_cart


def cart_context(request):
    """Provide cart_item_count and store metadata for templates."""
    count = 0
    try:
        cart = get_cart(request, create=False)
        if cart:
            count = cart.items.count()
    except Exception:
        count = 0
    return {
        "cart_item_count": count,
        "SUPPORT_EMAIL": getattr(settings, "SUPPORT_EMAIL", "support@virtusdigital.store"),
        "PRIVACY_EMAIL": getattr(settings, "PRIVACY_EMAIL", "privacy@virtusdigital.store"),
        "STORE_NAME": "Virtus",
    }
