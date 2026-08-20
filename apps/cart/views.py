from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.cart.forms import AddToCartForm
from apps.cart.models import CartItem
from apps.cart.services import get_cart
from apps.catalog.models import Product


@require_POST
def add_to_cart(request):
    form = AddToCartForm(request.POST)
    if form.is_valid():
        product = form.cleaned_data["product"]
        cart = get_cart(request)

        # Digital products: one row per (cart, product); adding again is a no-op.
        CartItem.objects.get_or_create(cart=cart, product=product)

        return redirect("cart:detail")

    # Invalid input: send the user back to the product page.
    product_id = request.POST.get("product")
    try:
        target = Product.objects.get(id=product_id).get_absolute_url()
    except (Product.DoesNotExist, ValueError, TypeError):
        target = reverse("catalog:product_list")
    messages.error(request, "Could not add that item to your cart.")
    return redirect(target)


def view_cart(request):
    cart = get_cart(request)
    items = list(cart.items.select_related("product"))
    subtotal_cents = sum(item.line_total_cents for item in items)
    return render(
        request,
        "cart/detail.html",
        {"cart": cart, "items": items, "subtotal_cents": subtotal_cents},
    )


@require_POST
def remove_from_cart(request, item_id):
    cart = get_cart(request)
    CartItem.objects.filter(cart=cart, id=item_id).delete()
    return redirect("cart:detail")
