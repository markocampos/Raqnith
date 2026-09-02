from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from config.admin import admin_site, pesos

from .models import PaymentAttempt, Refund, WebhookEvent

ATTEMPT_STATUS_COLORS = {
    PaymentAttempt.Status.CREATED: "#64748b",
    PaymentAttempt.Status.AWAITING_METHOD: "#d97706",
    PaymentAttempt.Status.AWAITING_ACTION: "#d97706",
    PaymentAttempt.Status.PROCESSING: "#1d4ed8",
    PaymentAttempt.Status.SUCCEEDED: "#15803d",
    PaymentAttempt.Status.FAILED: "#b91c1c",
    PaymentAttempt.Status.CANCELLED: "#64748b",
}

REFUND_STATUS_COLORS = {
    Refund.Status.PENDING: "#d97706",
    Refund.Status.SUCCEEDED: "#15803d",
    Refund.Status.FAILED: "#b91c1c",
}


def pill(label, color):
    return format_html(
        '<span style="background:{};color:#fff;padding:2px 10px;'
        'border-radius:10px;font-size:11px;font-weight:600">{}</span>',
        color,
        label,
    )


@admin.register(PaymentAttempt, site=admin_site)
class PaymentAttemptAdmin(admin.ModelAdmin):
    """Provider payment records — view only; they are created by the
    checkout flow and updated by webhook processing, never by hand."""

    list_display = [
        "id_short",
        "order_link",
        "status_badge",
        "amount_display",
        "payment_method",
        "paymongo_link",
        "created_at",
    ]
    list_filter = ["status", "provider", "payment_method"]
    search_fields = ["id", "paymongo_intent_id", "paymongo_payment_id", "order__id"]
    search_help_text = "Search by attempt ID, intent ID or order."
    list_select_related = ["order"]
    ordering = ["-created_at"]
    date_hierarchy = "created_at"
    readonly_fields = [field.name for field in PaymentAttempt._meta.fields] + ["paymongo_link"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="PayMongo Dashboard")
    def paymongo_link(self, obj):
        if not obj or not obj.id:
            return "-"
        if obj.paymongo_payment_id:
            url = f"https://dashboard.paymongo.com/payments/{obj.paymongo_payment_id}"
        elif obj.paymongo_intent_id:
            url = f"https://dashboard.paymongo.com/payments?search={obj.paymongo_intent_id}"
        else:
            url = "https://dashboard.paymongo.com/payments"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener" style="display:inline-flex;align-items:center;gap:3px;color:#2563eb;font-weight:600;text-decoration:none;">'
            'Open PayMongo ↗</a>',
            url,
        )

    @admin.display(description="Attempt")
    def id_short(self, obj):
        return str(obj.id)[:8]

    @admin.display(description="Order", ordering="order")
    def order_link(self, obj):
        url = reverse("admin:orders_order_change", args=[obj.order_id])
        return format_html('<a href="{}">{}</a>', url, str(obj.order_id)[:8])

    @admin.display(description="Amount", ordering="amount")
    def amount_display(self, obj):
        return pesos(obj.amount)

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        label = obj.get_status_display()
        color = ATTEMPT_STATUS_COLORS.get(obj.status, "#64748b")
        if obj.failure_code:
            label = f"{label} · {obj.failure_code}"
        return pill(label, color)


class RefundInline(admin.TabularInline):
    model = Refund
    extra = 0
    can_delete = False
    fields = [
        "status_badge_display",
        "amount_display",
        "reason",
        "provider_refund_id",
        "created_at",
    ]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Status")
    def status_badge_display(self, obj):
        return pill(
            obj.get_status_display(),
            REFUND_STATUS_COLORS.get(obj.status, "#64748b"),
        )

    @admin.display(description="Amount")
    def amount_display(self, obj):
        return pesos(obj.amount)


PaymentAttemptAdmin.inlines = [RefundInline]


@admin.register(Refund, site=admin_site)
class RefundAdmin(admin.ModelAdmin):
    """Refunds are recorded by the payment service. Staff may update the
    status/reason after completing a refund manually (e.g. from the
    PayMongo dashboard), but amounts and provider IDs stay immutable."""

    list_display = [
        "id_short",
        "payment_link",
        "amount_display",
        "status_badge",
        "reason",
        "provider_refund_id",
        "created_at",
    ]
    list_filter = ["status"]
    search_fields = ["id", "provider_refund_id", "payment__paymongo_intent_id"]
    search_help_text = "Search by refund ID, provider refund ID or intent."
    list_select_related = ["payment"]
    ordering = ["-created_at"]
    date_hierarchy = "created_at"
    readonly_fields = [
        "id",
        "payment",
        "amount",
        "provider_refund_id",
        "created_at",
        "updated_at",
    ]

    fieldsets = (
        (
            "Refund record",
            {
                "fields": ("id", "payment", "amount", "provider_refund_id", "created_at"),
                "description": "Created by the payment service — do not edit by hand.",
            },
        ),
        (
            "Resolution",
            {
                "fields": ("status", "reason", "failure_message"),
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    @admin.display(description="Refund")
    def id_short(self, obj):
        return str(obj.id)[:8]

    @admin.display(description="Payment")
    def payment_link(self, obj):
        url = reverse("admin:payments_paymentattempt_change", args=[obj.payment_id])
        return format_html('<a href="{}">{}</a>', url, str(obj.payment_id)[:8])

    @admin.display(description="Amount", ordering="amount")
    def amount_display(self, obj):
        return pesos(obj.amount)

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return pill(
            obj.get_status_display(),
            REFUND_STATUS_COLORS.get(obj.status, "#64748b"),
        )


@admin.register(WebhookEvent, site=admin_site)
class WebhookEventAdmin(admin.ModelAdmin):
    """Immutable audit log of provider callbacks. Failing events are
    reprocessed automatically; use this view to inspect payloads and errors."""

    list_display = [
        "event_type",
        "buyer",
        "order_link",
        "amount_display",
        "event_id_short",
        "processed_badge",
        "failure_count",
        "received_at",
    ]
    list_filter = ["processed", "event_type"]
    search_fields = ["provider_event_id", "event_type"]
    search_help_text = "Search by event type or provider event ID."
    ordering = ["-received_at"]
    date_hierarchy = "received_at"
    list_per_page = 50
    readonly_fields = [
        "id",
        "buyer_info",
        "provider_event_id",
        "event_type",
        "payload",
        "processed",
        "failure_count",
        "last_error",
        "received_at",
        "processed_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def _resolve_attempt(self, obj):
        if not hasattr(obj, "_cached_attempt"):
            payload = obj.payload or {}
            resource = payload.get("data", {}).get("attributes", {}).get("data", {})
            attrs = resource.get("attributes", {}) or {}
            intent_id = attrs.get("payment_intent_id")
            if intent_id:
                obj._cached_attempt = (
                    PaymentAttempt.objects.filter(paymongo_intent_id=intent_id)
                    .select_related("order__user")
                    .first()
                )
            else:
                obj._cached_attempt = None
        return obj._cached_attempt

    @admin.display(description="Buyer")
    def buyer(self, obj):
        attempt = self._resolve_attempt(obj)
        if attempt and attempt.order:
            email = attempt.order.email or (
                attempt.order.user.email if attempt.order.user else attempt.order.user.username
            )
            if email:
                return email
        payload = obj.payload or {}
        resource = payload.get("data", {}).get("attributes", {}).get("data", {})
        billing = resource.get("attributes", {}).get("billing") or {}
        if billing.get("email"):
            return billing["email"]
        return "-"

    @admin.display(description="Order")
    def order_link(self, obj):
        attempt = self._resolve_attempt(obj)
        if attempt and attempt.order_id:
            url = reverse("admin:orders_order_change", args=[attempt.order_id])
            return format_html('<a href="{}">#{}</a>', url, str(attempt.order_id)[:8])
        return "-"

    @admin.display(description="Amount")
    def amount_display(self, obj):
        attempt = self._resolve_attempt(obj)
        if attempt:
            return pesos(attempt.amount)
        payload = obj.payload or {}
        resource = payload.get("data", {}).get("attributes", {}).get("data", {})
        amt = resource.get("attributes", {}).get("amount")
        if amt is not None:
            return pesos(amt)
        return "-"

    @admin.display(description="Buyer & Order Summary")
    def buyer_info(self, obj):
        attempt = self._resolve_attempt(obj)
        if attempt and attempt.order:
            order = attempt.order
            email = order.email or (order.user.email if order.user else "-")
            url = reverse("admin:orders_order_change", args=[order.id])
            items = ", ".join(i.product_name for i in order.items.all()) or "Digital Goods"
            return format_html(
                '<div style="line-height: 1.6;">'
                '<strong>Customer Email:</strong> {}<br>'
                '<strong>Order:</strong> <a href="{}">#{}</a><br>'
                '<strong>Amount:</strong> {}<br>'
                '<strong>Items:</strong> {}'
                '</div>',
                email,
                url,
                order.id,
                pesos(order.total_amount),
                items,
            )
        return "No linked order found in payload."

    @admin.display(description="Provider Event ID")
    def event_id_short(self, obj):
        return obj.provider_event_id[:24]

    @admin.display(description="Processed", ordering="processed")
    def processed_badge(self, obj):
        if obj.processed:
            return pill("Processed", "#15803d")
        if obj.failure_count:
            return pill(f"Failing ×{obj.failure_count}", "#b91c1c")
        return pill("Unprocessed", "#d97706")

    @admin.display(description="Last error")
    def last_error(self, obj):
        text = obj.last_error or "-"
        return format_html("<span title='{}'>{}</span>", text, text[:60])
