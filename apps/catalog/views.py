from django.db.models import Count, Q
from django.views.generic import DetailView, ListView, TemplateView

from apps.catalog.models import Category, Product


class LandingPageView(TemplateView):
    template_name = "catalog/landing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        available_qs = Product.objects.filter(is_available=True).exclude(
            Q(category__name__icontains="test")
            | Q(category__slug__icontains="test")
            | Q(category__slug__icontains="smoke")
        )
        context["featured_products"] = available_qs.order_by("name")[:6]
        context["categories"] = (
            Category.objects.annotate(
                num_available_products=Count("products", filter=Q(products__is_available=True))
            )
            .filter(num_available_products__gt=0)
            .exclude(
                Q(name__icontains="test")
                | Q(slug__icontains="test")
                | Q(slug__icontains="smoke")
            )
            .order_by("name")
        )
        context["total_products_count"] = available_qs.count()
        return context


class ProductListView(ListView):
    model = Product
    template_name = "catalog/product_list.html"
    context_object_name = "products"
    paginate_by = 12

    def get_queryset(self):
        qs = Product.objects.filter(is_available=True).select_related("category").order_by("name")
        category_slug = self.request.GET.get("category", "").strip()
        if category_slug and category_slug != "all":
            qs = qs.filter(category__slug=category_slug)
        else:
            qs = qs.exclude(
                Q(category__name__icontains="test")
                | Q(category__slug__icontains="test")
                | Q(category__slug__icontains="smoke")
            )

        self.search_query = self.request.GET.get("q", "").strip()
        if self.search_query:
            qs = qs.filter(
                Q(name__icontains=self.search_query)
                | Q(description__icontains=self.search_query)
                | Q(category__name__icontains=self.search_query)
            )
        else:
            self.search_query = ""
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        categories = (
            Category.objects.annotate(
                num_available_products=Count("products", filter=Q(products__is_available=True))
            )
            .filter(num_available_products__gt=0)
            .exclude(
                Q(name__icontains="test")
                | Q(slug__icontains="test")
                | Q(slug__icontains="smoke")
            )
            .order_by("name")
        )
        context["categories"] = categories
        context["selected_category"] = self.request.GET.get("category", "all").strip()

        total_qs = Product.objects.filter(is_available=True).exclude(
            Q(category__name__icontains="test")
            | Q(category__slug__icontains="test")
            | Q(category__slug__icontains="smoke")
        )
        if getattr(self, "search_query", ""):
            total_qs = total_qs.filter(
                Q(name__icontains=self.search_query)
                | Q(description__icontains=self.search_query)
                | Q(category__name__icontains=self.search_query)
            )
        context["total_count"] = total_qs.count()
        context["search_query"] = getattr(self, "search_query", "")
        return context


class ProductDetailView(DetailView):
    model = Product
    template_name = "catalog/product_detail.html"
    context_object_name = "product"

    def get_queryset(self):
        return Product.objects.filter(is_available=True)
