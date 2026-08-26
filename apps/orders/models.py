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
    # Idempotency guard for the confirmation email (sent exactly once).
    confirmation_sent_at = models.DateTimeField(null=True, blank=True)
    # Idempotency guard for the "your QR expired — here's a fresh one"
    # recovery email sent while the order is still pending payment.
    recovery_email_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order {self.id}"

    @property
    def is_paid(self):
        return self.status == self.Status.PAID

    @property
    def is_expired(self):
        """Return True if this unpaid order has exceeded the 60-minute window."""
        if self.status in (self.Status.PAID, self.Status.FULFILLED, self.Status.CANCELLED):
            return False
        from datetime import timedelta

        from apps.orders.constants import ORDER_EXPIRATION_MINUTES
        return timezone.now() - self.created_at > timedelta(minutes=ORDER_EXPIRATION_MINUTES)

    def expire_if_overdue(self):
        """Automatically transition an overdue pending order to CANCELLED."""
        if self.status == self.Status.PENDING_PAYMENT and self.is_expired:
            self.transition_to(self.Status.CANCELLED)
            return True
        return False

    @classmethod
    def purge_unpaid_overdue(cls):
        """Permanently delete unpaid orders older than 30 days (1 month)."""
        from datetime import timedelta

        from apps.orders.constants import ORDER_PURGE_MINUTES
        from apps.payments.models import PaymentAttempt

        cutoff = timezone.now() - timedelta(minutes=ORDER_PURGE_MINUTES)
        stale_unpaid = cls.objects.filter(
            created_at__lte=cutoff,
            paid_at__isnull=True,
            status__in=[
                cls.Status.CANCELLED,
                cls.Status.PAYMENT_FAILED,
                cls.Status.DRAFT,
                cls.Status.PENDING_PAYMENT,
            ],
        )
        if not stale_unpaid.exists():
            return 0

        PaymentAttempt.objects.filter(order__in=stale_unpaid).delete()
        deleted_count, _ = stale_unpaid.delete()
        return deleted_count

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
    # Membership products only: when the buyer's access ends. NULL for
    # non-memberships (lifetime access) and for unlimited memberships.
    access_until = models.DateTimeField(null=True, blank=True)
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

    @property
    def is_membership(self):
        return (
            self.product_id
            and self.product.product_type == Product.ProductType.MEMBERSHIP
        )

    @property
    def has_active_access(self):
        """True while the buyer may use this item's files/links."""
        if not self.is_membership or self.access_until is None:
            return True
        return timezone.now() <= self.access_until

    @property
    def requires_license_key(self):
        return bool(
            self.product_id and self.product.requires_license_key
        )


class LicenseKey(models.Model):
    """A unique access code issued per order item for software products.

    Generated automatically the moment an order settles. Shown on the
    success/receipt pages, the confirmation email, and the PDF receipt.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_item = models.OneToOneField(
        OrderItem,
        related_name="license_key",
        on_delete=models.CASCADE,
    )
    key = models.CharField(max_length=40, unique=True, db_index=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["issued_at"]

    def __str__(self):
        return f"{self.key} ({self.order_item_id})"

    @property
    def is_active(self):
        return self.revoked_at is None


class DownloadLog(models.Model):
    """One row per served file download, used for rate limiting and audit.

    The per-order daily cap (settings.MAX_DOWNLOADS_PER_DAY_PER_ORDER) is
    computed from these rows; they also give support a trail when a buyer
    reports download problems.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, related_name="download_logs", on_delete=models.CASCADE)
    file = models.ForeignKey(
        "catalog.ProductFile",
        related_name="download_logs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order_id} ← {self.file} at {self.created_at:%Y-%m-%d %H:%M}"
