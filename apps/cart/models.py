import uuid

from django.conf import settings
from django.db import models

from apps.catalog.models import Product


class Cart(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="carts",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    session_key = models.CharField(max_length=40, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.id)


class CartItem(models.Model):
    """A single digital product in a cart. Digital goods have no quantity.

    Adding a product that is already in the cart is a no-op; the unique
    constraint guarantees one row per (cart, product).
    """

    cart = models.ForeignKey(Cart, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, related_name="cart_items", on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cart", "product"], name="unique_cart_product"),
        ]

    def __str__(self):
        return self.product.name

    @property
    def line_total_cents(self):
        return self.product.price_cents
