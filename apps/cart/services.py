from apps.cart.models import Cart, CartItem


def get_cart(request):
    """Return the cart for the current user or anonymous session, creating it if needed."""
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
        return cart

    session_key = request.session.session_key
    if not session_key:
        request.session.save()
        session_key = request.session.session_key

    cart, _ = Cart.objects.get_or_create(session_key=session_key)
    return cart


def merge_cart_on_login(request, user, old_session_key=None):
    """Transfer anonymous session cart items to the authenticated user's cart."""
    session_key = old_session_key or request.session.session_key
    if not session_key:
        return

    try:
        anon_cart = Cart.objects.get(session_key=session_key)
    except Cart.DoesNotExist:
        return

    user_cart, _ = Cart.objects.get_or_create(user=user)
    for item in list(anon_cart.items.all()):
        CartItem.objects.get_or_create(cart=user_cart, product=item.product)

    anon_cart.delete()
