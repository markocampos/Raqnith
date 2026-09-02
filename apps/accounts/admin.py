from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django.db.models import Count, Q, Sum

from apps.orders.models import Order
from config.admin import admin_site, pesos

from .models import User

# Nothing in Virtus uses permission groups; hide them to keep the
# admin index clean. Re-register if role-based staff access is needed.
try:
    admin_site.unregister(Group)
except NotRegistered:
    pass


class OrderInline(admin.TabularInline):
    model = Order
    extra = 0
    can_delete = False
    fields = ["id", "status", "total_amount", "created_at", "paid_at"]
    readonly_fields = fields
    ordering = ["-created_at"]
    verbose_name_plural = "Orders"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(User, site=admin_site)
class VirtusUserAdmin(UserAdmin):
    ordering = ["-date_joined"]
    list_display = [
        "email",
        "full_name",
        "order_count",
        "lifetime_spent",
        "active_flag",
        "staff_flag",
        "last_login_at",
        "date_joined",
    ]
    list_filter = UserAdmin.list_filter
    search_fields = ["username", "first_name", "last_name", "email"]
    search_help_text = "Search by username, name, or email."
    date_hierarchy = "date_joined"
    actions = ["activate_users", "deactivate_users"]
    inlines = [OrderInline]

    fieldsets = UserAdmin.fieldsets

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        paid = Q(orders__status__in=[Order.Status.PAID, Order.Status.FULFILLED])
        return qs.annotate(
            _order_count=Count("orders", distinct=True),
            _lifetime_spent=Sum("orders__total_amount", filter=paid),
        )

    @admin.display(description="Name", ordering="first_name")
    def full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip() or "-"

    @admin.display(description="Orders", ordering="_order_count")
    def order_count(self, obj):
        return obj._order_count

    @admin.display(description="Lifetime Spent", ordering="_lifetime_spent")
    def lifetime_spent(self, obj):
        return pesos(obj._lifetime_spent)

    @admin.display(description="Active", boolean=True)
    def active_flag(self, obj):
        return obj.is_active

    @admin.display(description="Staff", boolean=True)
    def staff_flag(self, obj):
        return obj.is_staff

    @admin.display(description="Last Login", ordering="last_login")
    def last_login_at(self, obj):
        return obj.last_login or "\u2014"

    @admin.action(description="Activate selected users")
    def activate_users(self, request, queryset):
        count = queryset.filter(is_active=False).update(is_active=True)
        self.message_user(request, f"{count} user(s) activated.")

    @admin.action(description="Deactivate selected users")
    def deactivate_users(self, request, queryset):
        count = queryset.filter(is_active=True).update(is_active=False)
        self.message_user(request, f"{count} user(s) deactivated.")
