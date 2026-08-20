from apps.cart.services import get_cart


def cart_context(request):
    """Provide cart_item_count for templates and navbar badge."""
    count = 0
    try:
        cart = get_cart(request)
        if cart:
            count = cart.items.count()
    except Exception:
        count = 0
    return {
        "cart_item_count": count,
    }
