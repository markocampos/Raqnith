import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.catalog.models import Product
from apps.fields import MoneyField


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"
        PAYMENT_FAILED = "payment_failed", "Payment failed"
        FULFILLED = "fulfilled", "Fulfilled"

    # Explicit lifecycle: every status change must go through one of these
    # edges. See transition_to().
    ALLOWED_TRANSITIONS = {
        Status.DRAFT: {Status.PENDING_PAYMENT, Status.CANCELLED},
        Status.PENDING_PAYMENT: {Status.PAID, Status.PAYMENT_FAILED, Status.CANCELLED},
        Status.PAYMENT_FAILED: {Status.PENDING_PAYMENT, Status.CANCELLED},
        Status.PAID: {Status.FULFILLED},
        Status.FULFILLED: set(),
        Status.CANCELLED: set(),
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="orders",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    session_key = models.CharField(
        max_length=40,
        null=True,
        blank=True,
        db_index=True,
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )

    subtotal_amount = MoneyField()
    discount_amount = MoneyField(default=0)
    total_amount = MoneyField()

    currency = models.CharField(max_length=3, default="PHP")

    # Customer contact/billing captured at checkout (never card data).
    email = models.CharField(max_length=254, blank=True)
    shipping_name = models.CharField(max_length=200, blank=True)
    shipping_phone = models.CharField(max_length=30, blank=True)
    shipping_address = models.CharField(max_length=200, blank=True)
    shipping_city = models.CharField(max_length=100, blank=True)
    shipping_postal = models.CharField(max_length=10, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order {self.id}"

    @property
    def is_paid(self):
        return self.status == self.Status.PAID

    def transition_to(self, status):
        """Move the order to ``status`` if the transition is allowed."""
        allowed = self.ALLOWED_TRANSITIONS.get(self.status, set())
        if status not in allowed:
            raise ValueError(f"Invalid order transition: {self.status} -> {status}.")

        self.status = status
        if status == self.Status.PAID and self.paid_at is None:
            self.paid_at = timezone.now()

        self.save(update_fields=["status", "paid_at", "updated_at"])
        return self


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, related_name="order_items", on_delete=models.PROTECT)
    product_name = models.CharField(max_length=200)
    unit_price_cents = MoneyField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["order", "product"], name="unique_order_product"),
        ]

    def __str__(self):
        return self.product_name

    @property
    def line_total_cents(self):
        return self.unit_price_cents
