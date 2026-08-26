from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from config.admin import admin_site

from apps.seller.models import SellerApplication


@admin.register(SellerApplication, site=admin_site)
class SellerApplicationAdmin(admin.ModelAdmin):
    list_display = [
        "brand_name",
        "full_name",
        "email",
        "category",
        "status_badge",
        "waiting_days",
        "created_at",
    ]
    list_filter = ["status", "category", "created_at"]
    search_fields = ["brand_name", "full_name", "email", "message"]
    list_per_page = 25
    date_hierarchy = "created_at"
    actions = ["mark_approved", "mark_declined"]

    # Applications arrive through the public form; staff review them here.
    def has_add_permission(self, request):
        return False

    # Everything except the Review decision is a read-only record of what
    # the applicant submitted — it must not be edited after the fact.
    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ["created_at"]
        return [
            "full_name",
            "email",
            "brand_name",
            "portfolio_url",
            "social_url",
            "category",
            "message",
            "created_at",
        ]

    fieldsets = (
        ("Applicant", {
            "fields": ("full_name", "email", "brand_name"),
        }),
        ("Work & Products", {
            "fields": ("portfolio_url", "social_url", "category", "message"),
        }),
        ("Review", {
            "fields": ("status", "reviewed_at", "created_at"),
            "description": (
                "The only editable section. Approved creators are onboarded "
                "by the store team; their products are curated and published "
                "via the admin, never self-serve."
            ),
        }),
    )

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        colors = {
            SellerApplication.Status.PENDING: "#d97706",
            SellerApplication.Status.APPROVED: "#15803d",
            SellerApplication.Status.DECLINED: "#b91c1c",
        }
        color = colors.get(obj.status, "#64748b")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;'
            'border-radius:10px;font-size:11px;font-weight:600">{}</span>',
            color,
            obj.get_status_display(),
        )

    @admin.display(description="Waiting")
    def waiting_days(self, obj):
        if obj.status != SellerApplication.Status.PENDING:
            return "-"
        days = (timezone.now() - obj.created_at).days
        return f"{days}d" if days else "today"

    @admin.action(description="Mark selected applications as Approved")
    def mark_approved(self, request, queryset):
        updated = queryset.exclude(status=SellerApplication.Status.APPROVED).update(
            status=SellerApplication.Status.APPROVED,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f"{updated} application(s) approved.")

    @admin.action(description="Mark selected applications as Declined")
    def mark_declined(self, request, queryset):
        updated = queryset.exclude(status=SellerApplication.Status.DECLINED).update(
            status=SellerApplication.Status.DECLINED,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f"{updated} application(s) declined.")
