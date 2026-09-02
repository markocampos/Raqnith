from django.contrib import admin
from django.db.models import Count, Sum
from django.utils import timezone

from config.admin import admin_site, pesos

from .models import Cart, CartItem


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    fields = ["product", "price_display"]
    readonly_fields = ["price_display"]
    autocomplete_fields = ["product"]

    @admin.display(description="Price")
    def price_display(self, obj):
        if not obj or not obj.product_id:
            return "-"
        return pesos(obj.product.price_cents)


class ActivityFilter(admin.SimpleListFilter):
    """Separate live carts from abandoned ones worth purging."""

    title = "activity"
    parameter_name = "activity"

    def lookups(self, request, model_admin):
        return (
            ("recent", "Active in last 30 days"),
            ("stale", "Untouched 30+ days"),
        )

    def queryset(self, request, queryset):
        cutoff = timezone.now() - timezone.timedelta(days=30)
        if self.value() == "recent":
            return queryset.filter(updated_at__gte=cutoff)
        if self.value() == "stale":
            return queryset.filter(updated_at__lt=cutoff)


@admin.register(Cart, site=admin_site)
class CartAdmin(admin.ModelAdmin):
    list_display = [
        "cart_id",
        "owner",
        "item_count",
        "cart_value",
        "updated_at",
        "created_at",
    ]
    list_display_links = ["cart_id", "owner"]
    list_filter = [ActivityFilter]
    search_fields = [
        "id",
        "session_key",
        "user__username",
        "user__email",
        "items__product__name",
    ]
    ordering = ["-updated_at"]
    list_select_related = ["user"]
    autocomplete_fields = ["user"]
    readonly_fields = ["id", "created_at", "updated_at"]
    inlines = [CartItemInline]

    fieldsets = (
        (
            "Cart",
            {
                "fields": ("id", "user", "session_key", "created_at", "updated_at"),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                _item_count=Count("items", distinct=True),
                _cart_value=Sum("items__product__price_cents"),
            )
        )

    @admin.display(description="Cart ID", ordering="id")
    def cart_id(self, obj):
        return str(obj.id)[:8]

    @admin.display(description="Shopper")
    def owner(self, obj):
        if obj.user_id:
            return obj.user.get_username()
        suffix = (obj.session_key or "")[:8]
        return f"Guest ({suffix}…)"

    @admin.display(description="Items", ordering="_item_count")
    def item_count(self, obj):
        return obj._item_count

    @admin.display(description="Cart Value", ordering="_cart_value")
    def cart_value(self, obj):
        return pesos(obj._cart_value)
