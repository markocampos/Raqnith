import uuid

from django.db import models

from apps.fields import MoneyField
from apps.orders.models import Order


class PaymentAttempt(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "Created"
        AWAITING_METHOD = "awaiting_method", "Awaiting method"
        AWAITING_ACTION = "awaiting_action", "Awaiting action"
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        Order,
        related_name="payment_attempts",
        on_delete=models.PROTECT,
    )
    provider = models.CharField(max_length=30, default="paymongo")
    paymongo_intent_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    paymongo_payment_id = models.CharField(max_length=100, blank=True)
    client_key = models.CharField(max_length=255, blank=True)
    qr_url = models.TextField(blank=True)
    redirect_url = models.TextField(blank=True)
    amount = MoneyField()
    currency = models.CharField(max_length=3, default="PHP")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.CREATED)
    payment_method = models.CharField(max_length=30, blank=True)
    failure_code = models.CharField(max_length=100, blank=True)
    failure_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Attempt {self.id} ({self.status})"

    @property
    def is_expired(self):
        """Return whether this QR payment attempt has expired (15m window)."""
        from datetime import timedelta

        from django.utils import timezone

        if self.status in (self.Status.SUCCEEDED, self.Status.CANCELLED):
            return False
        if self.failure_code in ("qr_expired", "qrph_expired"):
            return True
        return timezone.now() - self.created_at > timedelta(minutes=15)

    @property
    def seconds_remaining(self):
        """Return seconds remaining until QR code expiration."""
        from django.utils import timezone

        if self.status in (self.Status.SUCCEEDED, self.Status.CANCELLED, self.Status.FAILED):
            return 0
        elapsed = (timezone.now() - self.created_at).total_seconds()
        remaining = max(0, int(900 - elapsed))
        return remaining


class WebhookEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider_event_id = models.CharField(max_length=150, unique=True)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
    processed = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    # Monitoring: how many times processing failed and the last error, so the
    # webhook view can reprocess replays and alert an admin past a threshold.
    failure_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.event_type} {self.provider_event_id}"


class Refund(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(
        PaymentAttempt,
        related_name="refunds",
        on_delete=models.PROTECT,
    )
    amount = MoneyField()
    provider_refund_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    reason = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    failure_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Refund {self.id} ({self.status})"
