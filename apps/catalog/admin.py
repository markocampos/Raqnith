from django.contrib import admin

from .models import Category, Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ["name"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "category", "price_cents", "is_available", "created_at"]
    list_filter = ["is_available", "category"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
