from django.views.generic import DetailView, ListView, TemplateView

from apps.catalog.models import Category, Product


class LandingPageView(TemplateView):
    template_name = "catalog/landing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        available_qs = Product.objects.filter(is_available=True)
        context["featured_products"] = available_qs.order_by("name")[:6]
        context["categories"] = Category.objects.all()
        context["total_products_count"] = available_qs.count()
        return context


class ProductListView(ListView):
    model = Product
    template_name = "catalog/product_list.html"
    context_object_name = "products"
    queryset = Product.objects.filter(is_available=True).order_by("name")


class ProductDetailView(DetailView):
    model = Product
    template_name = "catalog/product_detail.html"
    context_object_name = "product"

    def get_queryset(self):
        return Product.objects.filter(is_available=True)
