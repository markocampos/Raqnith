from django import forms
from django.contrib import admin
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.html import format_html

from config.admin import admin_site

from .models import Category, Product, ProductFile

PESOS_MAX = 500_000


class ProductAdminForm(forms.ModelForm):
    """Staff enter prices in pesos; storage stays integer centavos."""

    price = forms.DecimalField(
        label="Price (\u20b1)",
        min_value=0,
        max_value=PESOS_MAX,
        max_digits=10,
        decimal_places=2,
        localize=True,
        help_text=(
            "Buyers pay this at checkout. Set anything under \u20b11 to offer "
            "this product completely free \u2014 checkout still confirms the "
            "order and delivers downloads, just without payment."
        ),
    )

    class Meta:
        model = Product
        exclude = ["price_cents"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["price"].initial = f"{self.instance.price_cents / 100:.2f}"

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.price_cents = int(self.cleaned_data["price"] * 100)
        if commit:
            obj.save()
        return obj


class ProductFileInline(admin.TabularInline):
    model = ProductFile
    extra = 1
    fields = ["name", "kind", "file", "external_url", "sort_order", "is_active"]
    ordering = ["sort_order", "created_at"]


class ProductInline(admin.TabularInline):
    model = Product
    form = ProductAdminForm
    extra = 1
    fields = ["name", "slug", "price", "is_available"]
    prepopulated_fields = {"slug": ("name",)}
    show_change_link = True


class DeliverableFilter(admin.SimpleListFilter):
    """Surface products that cannot be fulfilled because files are missing."""

    title = "deliverables"
    parameter_name = "files"

    def lookups(self, request, model_admin):
        return (
            ("missing", "Missing files"),
            ("ready", "Has files"),
        )

    def queryset(self, request, queryset):
        counted = queryset.annotate(
            _active_files=Count("files", filter=Q(files__is_active=True))
        )
        if self.value() == "missing":
            return counted.filter(_active_files=0)
        if self.value() == "ready":
            return counted.filter(_active_files__gt=0)


@admin.register(Category, site=admin_site)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "icon", "product_counts", "view_products_link"]
    list_editable = ["icon"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductInline]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                _total_products=Count("products", distinct=True),
                _live_products=Count(
                    "products",
                    filter=Q(products__is_available=True),
                    distinct=True,
                ),
            )
        )

    @admin.display(description="Products", ordering="_total_products")
    def product_counts(self, obj):
        return f"{obj._live_products} live / {obj._total_products} total"

    @admin.display(description="Quick Filter")
    def view_products_link(self, obj):
        url = reverse("admin:catalog_product_changelist") + f"?category__id__exact={obj.id}"
        return format_html(
            '<a href="{}" style="padding: 3px 8px;">View Products ({})</a>',
            url,
            obj._total_products,
        )


@admin.register(Product, site=admin_site)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = [
        "name",
        "category",
        "product_type",
        "price_display",
        "deliverables",
        "delivery_flags",
        "is_available",
        "created_at",
    ]
    list_filter = [
        "category",
        "product_type",
        "is_available",
        DeliverableFilter,
        "created_at",
    ]
    list_editable = ["is_available"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ["category"]
    date_hierarchy = "created_at"
    list_per_page = 25
    inlines = [ProductFileInline]
    actions = ["mark_as_available", "mark_as_unavailable"]

    fieldsets = (
        ("Product Information", {
            "fields": ("name", "slug", "category", "product_type", "price", "description", "is_available"),
            "description": "Select or create a Category, price, and customizable description for this digital product.",
        }),
        ("Delivery", {
            "fields": ("requires_license_key", "membership_duration_days"),
            "description": (
                "License key: auto-issues one access code per order at payment. "
                "Membership duration: days of file/link access from payment. "
                "Attach the buyer's files or links in the Deliverables section below."
            ),
        }),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(_active_files=Count("files", filter=Q(files__is_active=True)))
        )

    @admin.display(description="Price", ordering="price_cents")
    def price_display(self, obj):
        if obj.price_cents < 100:
            return format_html(
                '<span style="color:{}; font-weight:{};">Free</span>',
                "#15803d",
                "700",
            )
        return f"\u20b1{obj.price_cents / 100:,.2f}"

    @admin.display(description="Deliverables", ordering="_active_files")
    def deliverables(self, obj):
        if obj._active_files == 0:
            return format_html(
                '<span style="color:{}; font-weight:{};">Missing</span>',
                "#e62b1e",
                "700",
            )
        return f"{obj._active_files} file(s)"

    @admin.display(description="Delivery Options")
    def delivery_flags(self, obj):
        flags = []
        if obj.requires_license_key:
            flags.append("License key")
        if obj.membership_duration_days:
            flags.append(f"{obj.membership_duration_days}-day access")
        return ", ".join(flags) or "-"

    @admin.action(description="Mark selected products as In Stock / Available")
    def mark_as_available(self, request, queryset):
        count = queryset.update(is_available=True)
        self.message_user(request, f"{count} product(s) marked as available.")

    @admin.action(description="Mark selected products as Sold Out / Unavailable")
    def mark_as_unavailable(self, request, queryset):
        count = queryset.update(is_available=False)
        self.message_user(request, f"{count} product(s) marked as unavailable.")
