from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from config.admin import admin_site

from .models import Coupon


class ExpiryFilter(admin.SimpleListFilter):
    title = "expiry"
    parameter_name = "expiry"

    def lookups(self, request, model_admin):
        return (
            ("valid", "Valid (active & not expired)"),
            ("expired", "Expired"),
            ("never", "Never expires"),
        )

    def queryset(self, request, queryset):
        now = timezone.now()
        if self.value() == "valid":
            return queryset.filter(active=True).exclude(expires_at__lte=now)
        if self.value() == "expired":
            return queryset.filter(expires_at__lte=now)
        if self.value() == "never":
            return queryset.filter(expires_at__isnull=True)


@admin.register(Coupon, site=admin_site)
class CouponAdmin(admin.ModelAdmin):
    list_display = ["code", "discount_percent", "status_badge", "active", "expires_at", "created_at"]
    list_editable = ["active"]
    list_filter = ["active", ExpiryFilter]
    search_fields = ["code"]
    ordering = ["-created_at"]
    readonly_fields = ["created_at"]
    actions = ["mark_active", "mark_inactive"]

    fieldsets = (
        ("Discount", {
            "fields": ("code", "discount_percent", "active"),
            "description": "Buyers enter this code at checkout for a percentage off their order total.",
        }),
        ("Availability", {
            "fields": ("expires_at", "created_at"),
            "description": "Leave the expiry empty for a coupon that never expires.",
        }),
    )

    @admin.display(description="Status", ordering="active")
    def status_badge(self, obj):
        if obj.is_expired:
            color, label = "#b91c1c", "Expired"
        elif not obj.active:
            color, label = "#64748b", "Disabled"
        else:
            color, label = "#15803d", "Active"
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;'
            'border-radius:10px;font-size:11px;font-weight:600">{}</span>',
            color,
            label,
        )

    @admin.action(description="Activate selected coupons")
    def mark_active(self, request, queryset):
        count = queryset.update(active=True)
        self.message_user(request, f"{count} coupon(s) activated.")

    @admin.action(description="Disable selected coupons")
    def mark_inactive(self, request, queryset):
        count = queryset.update(active=False)
        self.message_user(request, f"{count} coupon(s) disabled.")
