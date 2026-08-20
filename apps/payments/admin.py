from django.contrib import admin

from .models import PaymentAttempt, Refund, WebhookEvent


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "order",
        "status",
        "amount",
        "currency",
        "payment_method",
        "provider",
        "paymongo_intent_id",
        "paymongo_payment_id",
        "failure_code",
        "failure_message",
        "created_at",
        "updated_at",
    ]
    list_filter = ["status", "provider"]
    search_fields = ["id", "paymongo_intent_id", "order__id"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "payment",
        "amount",
        "status",
        "provider_refund_id",
        "reason",
        "created_at",
    ]
    list_filter = ["status"]
    search_fields = ["id", "provider_refund_id", "payment__paymongo_intent_id"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ["provider_event_id", "event_type", "processed", "received_at", "processed_at"]
    list_filter = ["processed", "event_type"]
    search_fields = ["provider_event_id"]
    readonly_fields = [
        "provider_event_id",
        "event_type",
        "payload",
        "processed",
        "received_at",
        "processed_at",
    ]
