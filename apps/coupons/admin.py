from django.contrib import admin

from .models import Coupon


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ["code", "discount_percent", "active", "expires_at", "created_at"]
    list_filter = ["active"]
    search_fields = ["code"]
    readonly_fields = ["created_at"]
