from django.contrib import admin
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.payments.models import PaymentAttempt
from config.admin import admin_site, pesos

from .models import DownloadLog, LicenseKey, Order, OrderItem

STATUS_COLORS = {
    Order.Status.DRAFT: "#64748b",
    Order.Status.PENDING_PAYMENT: "#d97706",
    Order.Status.PAID: "#15803d",
    Order.Status.PAYMENT_FAILED: "#b91c1c",
    Order.Status.CANCELLED: "#64748b",
    Order.Status.FULFILLED: "#1d4ed8",
}


def status_pill(label, color):
    return format_html(
        '<span style="background:{};color:#fff;padding:2px 10px;'
        'border-radius:10px;font-size:11px;font-weight:600">{}</span>',
        color,
        label,
    )


class RevokedFilter(admin.SimpleListFilter):
    title = "status"
    parameter_name = "revocation"

    def lookups(self, request, model_admin):
        return (("active", "Active"), ("revoked", "Revoked"))

    def queryset(self, request, queryset):
        if self.value() == "active":
            return queryset.filter(revoked_at__isnull=True)
        if self.value() == "revoked":
            return queryset.filter(revoked_at__isnull=False)


@admin.register(LicenseKey, site=admin_site)
class LicenseKeyAdmin(admin.ModelAdmin):
    list_display = ["key", "order_link", "product_name", "status_badge", "issued_at"]
    list_filter = [RevokedFilter]
    search_fields = ["key", "order_item__product_name", "order_item__order__id"]
    list_select_related = ["order_item", "order_item__order"]
    ordering = ["-issued_at"]
    actions = ["revoke_keys"]
    readonly_fields = ["id", "key", "order_item", "issued_at", "revoked_at"]

    fieldsets = (
        (
            "License key",
            {
                "fields": ("key", "order_item", "issued_at"),
                "description": (
                    "Issued automatically the moment an order settles. Shown on "
                    "the receipt page and confirmation email."
                ),
            },
        ),
        (
            "Revocation",
            {
                "fields": ("revoked_at",),
                "description": "Revoking blocks further use of this key. It cannot be undone here.",
            },
        ),
    )

    def has_add_permission(self, request):
        return False  # keys are generated automatically at payment

    @admin.display(description="Order")
    def order_link(self, obj):
        order = obj.order_item.order
        url = reverse("admin:orders_order_change", args=[order.id])
        return format_html('<a href="{}">{}</a>', url, str(order.id)[:8])

    @admin.display(description="Product")
    def product_name(self, obj):
        return obj.order_item.product_name

    @admin.display(description="Status", ordering="revoked_at")
    def status_badge(self, obj):
        if obj.is_active:
            return status_pill("Active", "#15803d")
        return status_pill("Revoked", "#b91c1c")

    @admin.action(description="Revoke selected keys")
    def revoke_keys(self, request, queryset):
        count = queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        self.message_user(request, f"{count} license key(s) revoked.")


@admin.register(DownloadLog, site=admin_site)
class DownloadLogAdmin(admin.ModelAdmin):
    list_display = ["order_link", "file", "ip_address", "created_at"]
    search_fields = ["order__id", "file__name", "ip_address"]
    list_select_related = ["order", "file"]
    ordering = ["-created_at"]
    date_hierarchy = "created_at"
    readonly_fields = ["id", "order", "file", "ip_address", "user_agent", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Order")
    def order_link(self, obj):
        url = reverse("admin:orders_order_change", args=[obj.order.id])
        return format_html('<a href="{}">{}</a>', url, str(obj.order.id)[:8])


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ["product", "product_name", "unit_price_cents", "access_until"]
    autocomplete_fields = ["product"]


class PaymentAttemptInline(admin.TabularInline):
    model = PaymentAttempt
    extra = 0
    can_delete = False
    fields = [
        "status",
        "payment_method",
        "paymongo_intent_id",
        "failure_code",
        "failure_message",
    ]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order, site=admin_site)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        "order_id",
        "customer",
        "items_count",
        "total_display",
        "status_badge",
        "created_at",
        "paid_at",
    ]
    list_filter = ["status"]
    search_fields = ["id", "email", "shipping_name", "session_key"]
    search_help_text = "Search by order ID, email, name or session."
    list_select_related = ["user"]
    date_hierarchy = "created_at"
    list_per_page = 25
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "paid_at",
        "confirmation_sent_at",
        "recovery_email_sent_at",
    ]
    inlines = [OrderItemInline, PaymentAttemptInline]

    fieldsets = (
        (
            "Order",
            {
                "fields": ("id", "status", "created_at", "updated_at", "paid_at"),
                "description": (
                    "Status moves along a fixed path: Draft → Pending payment → "
                    "Paid → Fulfilled. Failed and cancelled orders may be retried "
                    "back to Pending payment while they are still fresh."
                ),
            },
        ),
        (
            "Customer contact",
            {
                "fields": ("email", "shipping_name", "shipping_phone"),
            },
        ),
        (
            "Billing address",
            {
                "fields": ("shipping_address", "shipping_city", "shipping_postal"),
            },
        ),
        (
            "Amounts (PHP)",
            {
                "fields": ("subtotal_amount", "discount_amount", "total_amount", "currency"),
            },
        ),
        (
            "Delivery emails",
            {
                "fields": ("confirmation_sent_at", "recovery_email_sent_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_item_count=Count("items", distinct=True))

    @admin.display(description="Order ID", ordering="id")
    def order_id(self, obj):
        return str(obj.id)[:8]

    @admin.display(description="Customer", ordering="email")
    def customer(self, obj):
        if obj.user_id:
            return obj.user.get_username()
        if obj.email:
            return obj.email
        return obj.session_key or "guest"

    @admin.display(description="Items", ordering="_item_count")
    def items_count(self, obj):
        return obj._item_count

    @admin.display(description="Total", ordering="total_amount")
    def total_display(self, obj):
        return pesos(obj.total_amount)

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        label = obj.get_status_display()
        return status_pill(label, STATUS_COLORS.get(obj.status, "#64748b"))
