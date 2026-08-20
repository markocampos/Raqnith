from django.contrib import admin

from apps.payments.models import PaymentAttempt

from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ["product", "product_name", "unit_price_cents"]


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


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "customer",
        "status",
        "total_amount",
        "currency",
        "created_at",
        "paid_at",
    ]
    list_filter = ["status"]
    search_fields = ["id", "email", "shipping_name"]
    readonly_fields = ["id", "created_at", "updated_at", "paid_at"]
    inlines = [OrderItemInline, PaymentAttemptInline]

    @admin.display(description="Customer")
    def customer(self, obj):
        if obj.user_id:
            return obj.user.get_username()
        if obj.email:
            return obj.email
        return obj.session_key or "guest"
